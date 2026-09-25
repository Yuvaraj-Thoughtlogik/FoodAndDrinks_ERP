import logging,re,base64
import requests
from dateutil import parser as date_parser
import pytz
import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import psycopg2
from datetime import date, datetime


def _safe_json(obj):
    """Convert non-serializable objects to serializable form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif hasattr(obj, 'id') and hasattr(obj, 'name'):  # likely a recordset
        return {'id': obj.id, 'name': obj.name}
    return str(obj)  # fallback for anything else



_logger = logging.getLogger(__name__)

# from cr_odoo_zoho_sync import ZohoConfig
IGNORED_REQUIRED_FIELDS = {
    'product.template': ['product_variant_ids'],
    'sale.order': ['order_line', 'partner_invoice_id', 'partner_shipping_id'],
    'purchase.order': ['order_line', 'currency_id'],
    'account.move': ['invoice_line_ids', 'journal_id', 'currency_id'],
    'stock.picking': ['move_ids_without_package', 'location_id', 'location_dest_id'],
    'stock.move': ['location_id', 'location_dest_id'],
    # Add more models as needed
}
# f"x_{self.zoho_app_name.replace(' ','_')}_{self.name.replace(' ','_')}_id"
def label_to_key(val):
    return re.sub(r'\s+', '_', val.strip().lower())

def key_to_label(key):
    key = re.sub(r'_+', ' ', key)            # Replace multiple underscores with space
    return key.title()

def parse_datetime_flexibly(val):
    """
    Attempt to parse a flexible datetime string or datetime object.
    Converts timezone-aware datetimes to naive UTC.

    Args:
        val (str | datetime.datetime): The input datetime string or object.

    Returns:
        (datetime | None, str | None): Parsed naive datetime or None, with an error message if failed.
    """
    if not val:
        return None, "Datetime input is empty or None."

    # If already a datetime object
    if isinstance(val, datetime):
        if val.tzinfo:
            val = val.astimezone(pytz.UTC).replace(tzinfo=None)
        return val, None

    # If input is a string, try to parse it
    if isinstance(val, str):
        try:
            dt = date_parser.parse(val)
            if dt.tzinfo:
                dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
            return dt, None
        except Exception as e:
            return None, f"Datetime parsing error: {str(e)}"

    return None, f"Unsupported datetime input type: {type(val).__name__}"

class ZohoConfigModule(models.Model):
    _inherit = 'zoho.config.module'

    module_name_id = fields.Many2one(comodel_name='zoho.import.module.name', string="Module Name ")

    def unlink(self):
        for rec in self:
            if rec.module_name_id:
                rec.module_name_id.imported = False
        return super().unlink()
    # zoho to odoo
    def get_data_from_zoho(self, zoho_module, fields_batch, last_sync=None, retry=True):
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise ValueError("Zoho configuration or access token is missing.")
        if config.regenerate_required:
            raise UserError(
                "Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}',
            'Content-Type': 'application/json'
        }

        field_list = list(fields_batch)
        # field_list.append('Modified_Time')
        field_chunks = [field_list[i:i + 50] for i in range(0, len(field_list), 50)]

        record_map = {}
        criteria = ""
        for field_chunk in field_chunks:
            fields_param = ",".join(field_chunk)
            base_url = f'{config.api_domain}/crm/v8/{zoho_module}?fields={fields_param}{criteria}'

            next_page_token = None
            while True:
                url = base_url
                if next_page_token:
                    url += f"&page_token={next_page_token}"

                response = requests.get(url, headers=headers)

                if response.status_code == 200:
                    response_json = response.json()
                    records = response_json.get('data', [])
                    for rec in records:
                        zoho_id = rec.get('id')
                        if not zoho_id:
                            continue
                        if zoho_id not in record_map:
                            record_map[zoho_id] = {}
                        record_map[zoho_id].update(rec)

                    info = response_json.get('info', {})
                    next_page_token = info.get('next_page_token') if info.get('more_records') else None
                    if not next_page_token:
                        break

                elif response.status_code == 401 and retry:
                    config.refresh_access_token()
                    return self.get_data_from_zoho(zoho_module, fields_batch,last_sync, retry=False)
                else:
                    raise Exception(f"Zoho API Error: {response.status_code} - {response.text}")

        return list(record_map.values())

    def get_record_detail_from_zoho(self, module_name, record_id,retry=True):
        """Fetch full record detail (including subforms) from Zoho"""
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise UserError("Zoho access token is missing.")
        if config.regenerate_required:
            raise UserError("Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        url = f"{config.api_domain}/crm/v8/{module_name}/{record_id}"
        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}',
            'Content-Type': 'application/json'
        }
        # print("brfore")
        response = requests.get(url, headers=headers)
        # print("Status Code:", response.status_code)  # 204
        # print("Headers:", response.headers)  # response headers
        # print("Text:", response.text)  # response body as string
        # print("Content:", response.content)

        if response.status_code == 401 and retry:
            config.refresh_access_token()
            return self.get_record_detail_from_zoho(module_name, record_id, retry=False)
        elif response.status_code == 201:
            raise UserError(f"Failed to fetch detailed Zoho record: No Record Found {response}")
        elif response.status_code != 200:
            raise UserError(f"Failed to fetch detailed Zoho record: {response}")


        return response.json().get('data', [{}])[0]

    def _download_zoho_file(self, file_id, retry=True):
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            return None, "Zoho configuration or access token is missing."
        if config.regenerate_required:
            raise UserError("Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}',
        }

        url = f"{config.api_domain}/crm/v8/files?id={file_id}"
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.content, None
        elif response.status_code == 401 and retry:
            config.refresh_access_token()
            return self._download_zoho_file(file_id, retry=False)
        else:
            try:
                error_json = response.json()
            except Exception:
                error_json = response.text
            return None, f"Failed to fetch file {file_id}: {error_json}"

    def _prepare_field_value_for_odoo(self, field, field_map, val):
        """Recursively prepares Zoho field value for Odoo field, including nested subforms."""
        field_type = field.ttype
        rel_model = field.relation

        try:
            if val in (None, '', [], {}):
                return None,None

            # === M2O ===
            if field_type == 'many2one':
                rel_id,error = self._get_or_create_zoho_related_record(rel_model, val, field_map)
                return rel_id,error

            # === M2M ===
            elif field_type == 'many2many':
                if isinstance(val, list):
                    rel_ids = []
                    for item in val:
                        # Try to extract Zoho value from sub-dict, or use item directly

                        zoho_val = item.get(field_map.name, {}) if isinstance(item, dict) else item
                        if field_map.name == "Tag":
                            zoho_val = item
                        if not zoho_val:
                            continue  # Skip empty/invalid items

                        rel_id, error = self._get_or_create_zoho_related_record(
                            rel_model, zoho_val, field_map)
                        if error:
                            return None, error
                        if rel_id:
                            rel_ids.append(rel_id)

                    return [(6, 0, rel_ids)], None  # Standard Odoo M2M replace command
                else:
                    return None, "Many2many must be provided as a list"

            # === O2M with Recursion ===
            elif field_type == 'one2many' and isinstance(val, list):
                sub_vals = [(5,0,0)]  # Clear existing one2many records
                sub_errors = []  # Collect field-level errors for reporting
                sub_model = self.env[field.relation]
                # zoho_id_field_name = f"x_{self.zoho_app_name.replace(' ', '_').lower()}_{self.name.replace(' ', '_').lower()}_{field_map.name.replace(' ', '_').lower()}_id"
                # zoho_id_field_label = f"{self.name.replace(' ', '_')} ID"
                if field_map.zoho_id_field_name not in sub_model._fields:
                    x_crm_zoho_id = self._add_custom_field(field.relation,field_map.zoho_id_field_name,'char','Zoho ID')
                for sub_item in val:
                    sub_rec = {}
                    item_errors = {}

                    if sub_item.get('id'):
                        sub_rec[field_map.zoho_id_field_name] = sub_item.get('id')
                    else:
                        continue
                    for sub_field in field_map.subform_field_ids:
                        sub_odoo_field = sub_field.odoo_field_id
                        odoo_key = sub_odoo_field.name
                        zoho_key = sub_field.name

                        sub_val = sub_item.get(zoho_key)
                        if sub_val in (None, '', [], {}):
                            continue

                        odoo_val, error = self._prepare_field_value_for_odoo(
                            sub_odoo_field, sub_field, sub_val)
                        # print(odoo_val,error)
                        if odoo_val is not None:
                            sub_rec[odoo_key] = odoo_val
                        if error:
                            item_errors[odoo_key] = {
                                'zoho_key': zoho_key,
                                'error': error,
                                'value': sub_val,
                            }

                    if sub_rec:
                        sub_vals.append((0, 0, sub_rec))
                    if item_errors:
                        sub_errors.append(item_errors)  # index as key for clarity
                # print("line674",sub_vals)
                return sub_vals if sub_vals else None,sub_errors if sub_errors else None


            # === Simple Field Types ===
            elif field_type in ['char','text','html']:

                return (val, None) if isinstance(val, (str,bool)) else (
                None, f"Expected string value, got: {val} ({type(val).__name__})")

            elif field_type == 'integer':
                try:
                    if isinstance(val, (int, float)):
                        return int(val), None
                    elif isinstance(val, str) and val.strip().isdigit():
                        return int(val.strip()), None
                    else:
                        return None, f"Expected integer-compatible value, got: {val} ({type(val).__name__})"
                except Exception as e:
                    return None, f"Integer conversion error: {str(e)}"

            elif field_type in ('float', 'monetary'):
                try:
                    if isinstance(val, (int, float)):
                        return float(val), None
                    elif isinstance(val, str):
                        val_str = val.strip().replace(',', '')
                        float_val = float(val_str)
                        return float_val, None
                    else:
                        return None, f"Expected float-compatible value, got: {val} ({type(val).__name__})"
                except Exception as e:
                    return None, f"Float conversion error: {str(e)}"

            elif field_type == 'boolean':
                if isinstance(val, bool):
                    return val, None
                elif isinstance(val, int) and val in (0, 1):
                    return bool(val), None
                elif isinstance(val, str):
                    val_lower = val.strip().lower()
                    if val_lower in ('true', 'yes', '1'):
                        return True, None
                    elif val_lower in ('false', 'no', '0'):
                        return False, None
                    else:
                        return None, f"Unrecognized boolean string: {val}"
                else:
                    return None, f"Expected boolean-compatible value, got: {val} ({type(val).__name__})"

            elif field_type in ['date','datetime']:
                return parse_datetime_flexibly(val)
                # return None,"Date and Time field handling is not implemented yet"

            elif field_type == 'selection':
                key,error = self.get_selection_key_or_value(self.odoo_model_name,field.name,val,check_as='label')
                return key if key else None, error if error else None

            elif field_type == 'binary':
                if isinstance(val, list) and val:
                    file_entry = val[0]  # Handle first file for now
                    file_id = file_entry.get('File_Id__s')
                    filename = file_entry.get('File_Name__s', 'file')

                    if not file_id:
                        return None, "Missing File_Id__s in File_Data"

                    try:
                        # Download file using Zoho API
                        file_data, error = self._download_zoho_file(file_id)
                        if file_data:
                            encoded = base64.b64encode(file_data).decode()
                            # return {'value': encoded, 'filename': filename}, None
                            return encoded, None
                        if error:
                            return None,error

                    except Exception as e:
                        return None, f"Error downloading file: {str(e)}"

                return None, f"Expected File_Data list for binary field, got: {type(val).__name__}"

            return None, f"Unhandled field type '{field_type}' for field '{field.name}'"

        except Exception as e:
            return None,f"[ZOHO] Error preparing value for {field_map.name}: {field_map.odoo_field_name}: {e}"

    def sync_zoho_to_odoo(self, last_sync=None, for_test=None):
        self.ensure_one()
        module = self
        created, updated, errors, unchanged = [], [], [], []
        response = {}
        request = []

        try:
            odoo_model = self.env[module.odoo_model.model]

            # Ensure Zoho ID field exists in model
            if self.zoho_id_field not in odoo_model._fields:
                self._add_custom_field(odoo_model._name, self.zoho_id_field, 'char', "Zoho ID")

            # print(module.name, for_test)

            # === Fetch Records ===
            if for_test and isinstance(for_test, (str, int)):
                record = self.get_record_detail_from_zoho(module.name, for_test)
                if not record:
                    errors.append({
                        'zoho_id': str(for_test),
                        'fetch_error': f"Record with Zoho ID {for_test} not found in module {module.name}"
                    })
                    return {
                        "status": "failed",
                        "odoo_model": module.odoo_model.model,
                        "zoho_model": module.name,
                        "request": request,
                        "response": {
                            "created": created,
                            "updated": updated,
                            "errors": errors
                        }
                    }
                records = [record]
            else:
                records = self.get_data_from_zoho(
                    module.name,
                    [field.name for field in self.fields_ids],
                    module.last_one_way_sync
                )

            has_subforms = any(field.field_type in ['many2many', 'one2many'] for field in module.fields_ids)

            # === Process Each Record ===
            for rec in records:
                try:
                    zoho_record_id = str(rec.get('id', ''))
                    if not zoho_record_id:
                        continue

                    modified_time = str(rec.get('Modified_Time', ''))
                    modified_time = parse_datetime_flexibly(modified_time)[0]

                    if has_subforms:
                        try:
                            rec = self.get_record_detail_from_zoho(module.name, zoho_record_id)
                        except Exception as e:
                            errors.append({
                                'zoho_id': zoho_record_id,
                                'error': f"Failed to fetch full subform data from Zoho:\n{e}"
                            })
                            continue

                    odoo_vals = {}
                    rec_request = {}
                    value_errors = {}

                    for field_map in self.fields_ids:
                        zoho_field = field_map.name.strip()
                        odoo_field = field_map.odoo_field_id
                        val = rec.get(zoho_field, field_map.default_value or False)

                        try:
                            processed_val, error = self._prepare_field_value_for_odoo(odoo_field, field_map, val)
                            rec_request[odoo_field.name] = val

                            if processed_val is not None:
                                odoo_vals[odoo_field.name] = processed_val
                            if error:
                                value_errors[odoo_field.name] = {
                                    'zoho_key': zoho_field,
                                    'error': error,
                                    'value': val
                                }
                        except Exception as err:
                            value_errors[odoo_field.name] = {
                                'zoho_key': zoho_field,
                                'error': str(err),
                                'value': val
                            }
                            continue

                    request.append({
                        'zoho_id': zoho_record_id,
                        'data': rec_request
                    })

                    # === Create or Update ===
                    existing = odoo_model.search([(self.zoho_id_field, '=', zoho_record_id)], limit=1)
                    if existing:
                        if last_sync and modified_time and modified_time < last_sync:
                            unchanged.append({
                                'zoho_id': zoho_record_id,
                                'status': 'unchanged'
                            })
                            continue
                        try:
                            with self.env.cr.savepoint():
                                existing.write(odoo_vals)

                                updated.append({
                                    'zoho_id': zoho_record_id,
                                    'odoo_id': existing.id,
                                    'status': 'success'
                                })
                        except psycopg2.Error as postgres_e:
                            errors.append({
                                'type': type(postgres_e).__name__,
                                'error': self.format_postgres_error(postgres_e)
                            })
                        except Exception as e:
                            errors.append({
                                'type': type(e).__name__,
                                'error':str(e)
                            })
                            continue

                    else:
                        odoo_vals[self.zoho_id_field] = zoho_record_id
                        # print(odoo_vals)
                        try:
                            # print('inside')
                            with self.env.cr.savepoint():
                                new_rec = odoo_model.create(odoo_vals)

                                created.append({
                                    'zoho_id': zoho_record_id,
                                    'odoo_id': new_rec.id,
                                    'status': 'success'
                                })
                        except psycopg2.Error as postgres_e:
                            errors.append({
                                'type': type(postgres_e).__name__,
                                'error': self.format_postgres_error(postgres_e)
                            })
                        except Exception as e:
                            errors.append({
                                'zoho_id': zoho_record_id,
                                'type': type(e).__name__,
                                'error': self.format_postgres_error(e),
                                # 'traceback': traceback.format_exc(limit=1),
                            })
                            continue


                    if value_errors:
                        errors.append({
                            'zoho_id': zoho_record_id,
                            'type': 'value_errors',
                            'fields': value_errors
                        })

                except Exception as sync_error:
                    errors.append({
                        'zoho_id': rec.get('id', ''),
                        'type': type(sync_error).__name__,
                        'error': str(sync_error)
                    })
                    continue

            response['created'] = created
            response['updated'] = updated
            response['errors'] = errors
            response['unchanged'] = unchanged

            return {
                "status": "success" if created or updated or unchanged else "failed",
                "odoo_model": module.odoo_model.model,
                "zoho_model": module.name,
                "request": request,
                "response": response
            }
        except psycopg2.Error as postgres_e:
            errors.append({
                'type': type(postgres_e).__name__,
                'error': self.format_postgres_error(postgres_e)
            })
            return {
                "status": "failed",
                "odoo_model": module.odoo_model.model if module.odoo_model else None,
                "zoho_model": module.name,
                "request": request,
                "response": {
                    "created": created,
                    "updated": updated,
                    "errors": errors
                }
            }

        except Exception as fatal_error:
            errors.append({
                'type': type(fatal_error).__name__,
                'error': str(fatal_error)
            })
            return {
                "status": "failed",
                "odoo_model": module.odoo_model.model if module.odoo_model else None,
                "zoho_model": module.name,
                "request": request,
                "response": {
                    "created": created,
                    "updated": updated,
                    "errors": errors
                }
            }

    #Odoo to Zoho
    def push_records_to_zoho(self, zoho_module, records_batch, method="POST", retry=True):
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise ValueError("Zoho configuration or access token is missing.")
        if config.regenerate_required:
            raise UserError("Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}',
            'Content-Type': 'application/json'
        }

        request_func = {
            "POST": requests.post,
            "PUT": requests.put
        }.get(method.upper())

        if not request_func:
            raise ValueError(f"Invalid method: {method}. Use 'POST' or 'PUT'.")

        all_responses = []

        # Chunking the records (max 100)
        for i in range(0, len(records_batch), 100):
            chunk = records_batch[i:i + 100]
            payload = {"data": chunk}
            url = f'{config.api_domain}/crm/v8/{zoho_module}'
            response = request_func(url, json=payload, headers=headers)

            # if response.status_code in [200, 201, 202]:
            #     all_responses.append(response.json())
            if response.status_code == 401 and retry:
                config.refresh_access_token()
                return self.push_records_to_zoho(zoho_module, records_batch, method=method, retry=False)
            else:
                all_responses.append(response.json())

        # Merge all responses if needed
        if len(all_responses) == 1:
            return all_responses[0]
        else:
            merged = {"data": []}
            for res in all_responses:
                merged["data"].extend(res.get("data", []))
            return merged

    def _check_zoho_id_exists(self, zoho_module, x_crm_zoho_id, retry=False):
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise ValueError("Zoho configuration or access token is missing.")
        if config.regenerate_required:
            raise UserError("Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}',
            'Content-Type': 'application/json'
        }

        url = f'{config.api_domain}/crm/v8/{zoho_module}/{x_crm_zoho_id}'
        response = requests.get(url, headers=headers)

        if response.status_code in [200, 201, 202]:
            return True
        elif response.status_code == 401 and retry:
            config.refresh_access_token()
            return self._check_zoho_id_exists(zoho_module, x_crm_zoho_id, retry=False)
        else:
            return False

    def multilookup_get_ids(self,zoho_module,rec_id, fields_maps, retry=True):
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise ValueError("Zoho configuration or access token is missing.")
        if config.regenerate_required:
            raise UserError("Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}',
            'Content-Type': 'application/json'
        }
        url = f'{config.api_domain}/crm/v8/{zoho_module}/{rec_id}?fields={fields_maps}'
        response = requests.get(url, headers=headers)
        if response.status_code == 401 and retry:
            config.refresh_access_token()
            return self.multilookup_get_ids(zoho_module,rec_id, fields_maps, retry=False)
        return response

    def delete_existing_multilookup_from_zoho(self, zoho_module, zoho_ids, field_names):
        all_responses = []

        for zoho_id in zoho_ids:
            update_payload = {'id': zoho_id}
            fields_batch = ','.join(field_names)
            response = self.multilookup_get_ids(zoho_module,zoho_id, fields_batch)

            if response.status_code != 200:
                continue

            resp_data = response.json().get('data', [])
            if not resp_data:
                continue

            record_data = resp_data[0]

            for field_name in field_names:
                field_values = record_data.get(field_name, [])
                deletions = []
                if not field_values:
                    continue
                for val in field_values:
                    if not val:
                        continue
                    record_id = val.get("id")
                    if record_id:
                        deletions.append({
                            "id": record_id,
                            "_delete": None
                        })

                if deletions:
                    update_payload[field_name] = deletions

            all_responses.append(update_payload)

        # print("all", all_responses)

        # Push updates in a single call
        update_response = self.push_records_to_zoho(zoho_module, all_responses, method="PUT")
        # print(update_response)

    def _upload_file_to_zoho(self, filename, file_content, retry=True):
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise ValueError("Zoho configuration or access token is missing.")
        if config.regenerate_required:
            raise UserError("Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        try:
            decoded = base64.b64decode(file_content)
        except Exception as e:
            return None

        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}'
        }

        files = {
            'file': (filename, decoded)
        }

        url = f"{config.api_domain}/crm/v8/files"

        response = requests.post(url, headers=headers, files=files)

        if response.status_code == 200:
            res_json = response.json()
            file_id = res_json['data'][0].get('details', {}).get('id')
            return file_id
        elif response.status_code == 401 and retry:
            config.refresh_access_token()
            return self._upload_file_to_zoho(filename, file_content, retry=False)
        else:
           return None

    def _prepare_field_value_for_zoho(self, field_map, record,zoho_id=None):
        field = field_map.odoo_field_id
        field_type = field.ttype
        odoo_field = field.name
        value = record[odoo_field]

        # zoho_id_field_label = f"{self.zoho_app_name} {field_map.zoho_lookup_module} ID"
        if value is None:
            return None

        # Handle many2one
        if field_type == 'many2one':

            relation_model = field.relation
            odoo_model = self.env[relation_model]

            if field_map.is_non_lookup:
                name_field = next((f for f in ['name', 'x_name'] if f in odoo_model._fields), None)
                if not name_field:
                    name_field = next((f.name for f in odoo_model._fields.values() if f.type == 'char'), None)
                return value[name_field] or ''
            # zoho_id_field_name = f"x_{self.zoho_app_name.strip().replace(' ', '_').lower()}_{field_map.zoho_lookup_module.strip().replace(' ', '_').lower()}_id"
            x_crm_zoho_id = getattr(value, field_map.zoho_id_field_name, None)
            if field_map.zoho_id_field_name in odoo_model._fields:
                if x_crm_zoho_id and self._check_zoho_id_exists(field_map.zoho_lookup_module, x_crm_zoho_id):
                    return {'id': x_crm_zoho_id}
            return None

        # Handle many2many
        elif field_type == 'many2many':
            relation_model = field.relation
            odoo_model = self.env[relation_model]
            result = []
            # zoho_id_field_name = ''
            # if not field_map.is_non_lookup:
                # zoho_id_field_name = f"x_{self.zoho_app_name.strip().replace(' ', '_').lower()}_{field_map.zoho_lookup_module.strip().replace(' ', '_').lower()}_id"
            for rec in value:
                if field_map.is_non_lookup:
                    name_field = next((f for f in ['name', 'x_name'] if f in odoo_model._fields), None)
                    if not name_field:
                        name_field = next((f.name for f in odoo_model._fields.values() if f.type == 'char'), None)
                    result.append(rec[name_field] or '')
                elif field_map.zoho_id_field_name in odoo_model._fields:
                    x_crm_zoho_id = getattr(rec, field_map.zoho_id_field_name, None)
                    check_exits =True if field_map.zoho_lookup_module == 'Tag' else self._check_zoho_id_exists(field_map.zoho_lookup_module, x_crm_zoho_id)
                    if field_map.zoho_id_field_name and check_exits:
                        result.append({
                            field_map.name: {'id': x_crm_zoho_id}
                        })
            return result

        # Handle one2many
        elif field_type == 'one2many':
            result = []
            # zoho_id_field_name = f"x_{self.zoho_app_name.strip().replace(' ', '_').lower()}_{field_map.zoho_lookup_module.strip().replace(' ', '_').lower()}_id"
            line_response = self.multilookup_get_ids(self.name,zoho_id,field_map.name)
            try:
                json_data = line_response.json()
            except ValueError:
                _logger.warning(
                    f"[ZOHO SYNC] Failed to decode JSON response for record {record.id}, field '{field_map.name}'. Raw response: {line_response.text}")
                json_data = {}

            data = json_data.get('data', [])
            lines = data[0].get(field_map.name, []) if data else []
            line_ids = [line.get('id') for line in lines if line.get('id')] if lines else []
            for val in value:
                sub_dict = {}

                zoho_line_id = getattr(val,field_map.zoho_id_field_name)
                if zoho_line_id:
                    sub_dict['id'] = zoho_line_id
                    if zoho_line_id in line_ids:
                        line_ids.remove(zoho_line_id)

                for subfield in field_map.subform_field_ids:
                    zoho_subfield = subfield.name
                    odoo_sub_val = self._prepare_field_value_for_zoho(subfield, val)
                    sub_dict[zoho_subfield] = odoo_sub_val

                result.append(sub_dict)
            for line_id in line_ids:
                result.append({
                    'id':line_id,
                    '_delete':None
                })
            return result

        # Handle simple fields
        elif field_type in ['char', 'text', 'html']:
            return value or None

        elif field_type == 'boolean':
            return bool(value)

        elif field_type in ['float', 'monetary', 'integer']:
            return value if value is not False else None

        elif field_type in ['date', 'datetime']:
            return value.isoformat() if value else None

        elif field_type == 'selection':
            if value:
                return key_to_label(value)
            return None

        elif field_type == 'binary':
            file_name = record[f'{odoo_field}_filename'] or 'file'
            # print(value)
            if value:
                file_id = self._upload_file_to_zoho(file_name, value)
                if file_id:
                    return [{'File_Id__s':file_id}]

            return None

        return None

    def _handle_subform_for_zoho(self,field_map, record,zoho_id=None):
        field = field_map.odoo_field_id
        field_type = field.ttype
        odoo_field = field.name
        value = record[odoo_field]
        zoho_id_field_name = f"x_{self.zoho_app_name.replace(' ', '_').lower()}_{field_map.zoho_lookup_module.replace(' ', '_').lower()}_id"
        zoho_id_field_label = f"{self.zoho_app_name} {field_map.zoho_lookup_module} ID"
        if value is None:
            return None
        x_crm_zoho_id = getattr(value, zoho_id_field_name, None)
        if field_type == 'one2many':
            result = []
            line_response = self.multilookup_get_ids(self.name, zoho_id, field_map.name)
            data = line_response.json().get('data', [])
            lines = data[0].get(field_map.name, []) if data else []
            line_ids = [line.get('id') for line in lines if line.get('id')] if lines else []
            zoho_ids = []
            for val in value:
                sub_dict = {}
                if val[zoho_id_field_name]:
                    sub_dict['id'] = val[zoho_id_field_name]
                    line_ids.remove(val[zoho_id_field_name])
                for subfield in field_map.subform_field_ids:
                    zoho_subfield = subfield.name
                    odoo_sub_val = self._prepare_field_value_for_zoho(subfield, val)
                    sub_dict[zoho_subfield] = odoo_sub_val

                result.append(sub_dict)
            for line_id in line_ids:
                result.append({
                    'id': line_id,
                    '_delete': None
                })
            return result

    def sync_odoo_to_zoho(self, last_sync = None, for_test=None):
        self.ensure_one()
        module = self
        create_batch = {}
        update_batch = {}
        created, updated, errors,unchanged = [],[],[],[]
        response_msg = {
        }
        request_msg = []
        def return_message(re_errors,re_odoo_model=None):
            return {
                "status": 'failed',
                "odoo_model": re_odoo_model,
                "zoho_model": module.name,
                "request": {},
                "response": {
                    "created":[],
                    "updated":[],
                    "unchanged":[],
                    "errors":re_errors
                }
            }

        if not module.odoo_model:
            errors.append(f"Odoo model not set for module {module.name}")
            return return_message(errors)

        odoo_model = self.env[module.odoo_model.model]

        zoho_id_field_name = self.zoho_id_field
        zoho_id_field_label = f"{self.zoho_app_name} {self.name} ID"

        if self.zoho_id_field not in odoo_model._fields:
            self._add_custom_field(odoo_model._name, self.zoho_id_field, 'char', 'Zoho ID')

        domain = []
        if for_test:
            domain = [('id', '=', int(for_test))] if isinstance(for_test, int) else []

        default_domain = [
            (field_map.odoo_field_name, '=',
             field_map.default_value if field_map.field_type != 'boolean' else (field_map.default_value or "").lower() == "true")
            for field_map in self.fields_ids if field_map.is_default
        ]

        if default_domain:
            domain.extend(default_domain)
        # print(domain)
        records = odoo_model.search(domain)
        # print(records)
        if not records:
            errors.append(f"No records found to sync {odoo_model._name}")
            return return_message(errors)
        many2many_fields = [field_map.name for field_map in self.fields_ids if field_map.field_type in ['many2many'] and not field_map.is_non_lookup]
        one2many_fields = [field_map for field_map in self.fields_ids if field_map.field_type in ['one2many'] and not field_map.is_non_lookup]
        zoho_ids = []
        for rec in records:
            try:
                zoho_data = {}
                request_data ={}
                for field_map in self.fields_ids:
                    zoho_field = field_map.name
                    zoho_val = self._prepare_field_value_for_zoho(field_map, rec,zoho_id=rec[zoho_id_field_name])
                    request_data[zoho_field] = zoho_val
                    if zoho_val is not None:
                        zoho_data[zoho_field] = zoho_val
                request_msg.append({
                    'odoo_id': rec.id,
                    'data': request_data
                })

                if rec[zoho_id_field_name] and self._check_zoho_id_exists(self.name, rec[zoho_id_field_name]):
                    if rec.write_date and last_sync and rec.write_date < last_sync:
                        unchanged.append({
                            'odoo_id': rec.id,
                            'zoho_id':rec[zoho_id_field_name]
                        })
                        continue
                    zoho_ids.append(rec[zoho_id_field_name])
                    zoho_data["id"] = rec[zoho_id_field_name]
                    update_batch[rec.id] = {"record": rec, "data": zoho_data}
                else:
                    create_batch[rec.id] = {"record": rec, "data": zoho_data}

            except Exception as e:
                _logger.warning(f"[ZOHO SYNC] Skipping record ID {rec.id} due to error: {e}")
                errors.append({
                    "record_id": rec.id,
                    'type': type(e).__name__,
                    "error": str(e)
                })
                request_msg.append({
                    'odoo_id': rec.id,
                    'error': str(e)
                })
                continue

        if many2many_fields:
            self.delete_existing_multilookup_from_zoho(module.name,zoho_ids,many2many_fields)



        # Push create batch
        if create_batch:
            # print(create_batch)
            create_batch_data = [v["data"] for v in create_batch.values()]
            # created_ids = {}

            _logger.info(f"[ZOHO SYNC] Creating {len(create_batch_data)} records in Zoho")

            try:
                all_response = self.push_records_to_zoho(module.name, create_batch_data, method='POST')
                data = all_response.get('data', [])

                for rec_id, response in zip(create_batch.keys(), data):
                    rec = create_batch[rec_id]["record"]  # get the record
                    if response.get('status') == 'success':
                        new_id = response.get('details', {}).get('id')
                        rec.write({zoho_id_field_name: new_id or ""})
                        created.append({"odoo_id": rec.id, "zoho_id": new_id, "status": "success"})
                        # all_zoho.append({"odoo_rec": rec, "zoho_id": new_id})
                    else:
                        errors.append({"odoo_id": rec.id, "status": "failed", "error": response})

            except Exception as e:
                errors.append({
                    "status": "failed",
                    'type': type(e).__name__,
                    "error": e
                })

        # Push update batch
        if update_batch:
            # print(update_batch)
            update_batch_data = [v["data"] for v in update_batch.values()]

            _logger.info(f"[ZOHO SYNC] Updating {len(update_batch_data)} records in Zoho")
            try:
                response = self.push_records_to_zoho(module.name, update_batch_data, method='PUT')
                data = response.get('data', [])

                for rec_id, res in zip(update_batch.keys(), data):
                    rec = update_batch[rec_id]["record"]
                    zoho_id = res.get('details', {}).get('id')
                    if res.get('status') == 'success':
                        updated.append({"odoo_id": rec.id, "zoho_id": zoho_id, "status": "success"})
                        # all_zoho.append({"odoo_rec": rec, "zoho_id": zoho_id})
                    else:
                        errors.append({"odoo_id": rec.id, "zoho_id": zoho_id, "status": "failed", "error": res})

            except Exception as e:
                errors.append({
                    "status": "failed",
                    'type': type(e).__name__,
                    "error": e
                })

        for batch in created + updated:
            rec = self.env[module.odoo_model.model].browse(batch["odoo_id"])
            zoho_id = batch["zoho_id"]
            # print([field.name for field in one2many_fields])
            zoho_fields = ','.join([field.name for field in one2many_fields])
            response = self.multilookup_get_ids(self.name, zoho_id, zoho_fields)
            # print("response",response)
            if response.status_code != 200:
                continue

            resp_data = response.json().get('data', []) if response else []
            # print(resp_data)
            if not resp_data:
                continue

            record_data = resp_data[0] if resp_data else []
            # print(record_data)
            # print(one2many_fields)
            for one2many in one2many_fields:
                odoo_subforms = getattr(rec, one2many.odoo_field_name)  # instead of rec[one2many]
                # print(odoo_subforms)
                zoho_subforms = [r.get("id") for r in record_data.get(one2many.name, [])]

                for row_index, subform in enumerate(odoo_subforms, start=0):
                    # print("subform",subform)
                    # print(one2many.zoho_id_field_name,zoho_subforms[row_index])
                    subform.write({
                        one2many.zoho_id_field_name: (
                            zoho_subforms[row_index] if len(zoho_subforms) > row_index else ""
                        )
                    })

        response_msg['created'] = created
        response_msg['updated'] = updated
        response_msg['errors'] = errors
        response_msg['unchanged'] = unchanged
        return {
            "status": "success" if created or updated or unchanged else 'failed',
            "odoo_model": module.odoo_model.model,
            "zoho_model":module.name,
            "request":request_msg,
            "response": response_msg
        }

    #Notes
    def _sync_zoho_notes_for_record(self, odoo_record, zoho_module, zoho_record_id):
        """Sync Zoho Notes for a specific record"""
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise UserError("Zoho configuration or access token is missing.")
        if config.regenerate_required:
            raise UserError("Region or scopes have changed. New authorization is required. Please regenerate your credentials.")
        if 'x_crm_zoho_id' not in self.env['mail.message']._fields:
            self._add_custom_field('mail.message', 'x_crm_zoho_id', 'char', 'Zoho Note ID')

        headers = {
            'Authorization': f'Zoho-oauthtoken {config.cr_access_token}',
            'Content-Type': 'application/json'
        }

        url = f"{config.api_domain}/crm/v8/{zoho_module}/{zoho_record_id}/Notes"
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return  # Optionally log or raise error

        notes = response.json().get("data", [])
        # print('notes-->',notes)
        for note in notes:
            content = note.get('Note_Content')
            title = note.get('Note_Title') or 'Zoho Note'
            zoho_note_id = note.get('id')

            existing = self.env['mail.message'].search([
                ('model', '=', odoo_record._name),
                ('res_id', '=', odoo_record.id),
                ('x_crm_zoho_id', '=', zoho_note_id)
            ], limit=1)

            if not existing:
                odoo_record.message_post(
                    body=content or '(No content)',
                    subject=title,
                    message_type='comment',
                    **{'x_crm_zoho_id': zoho_note_id}
                )


