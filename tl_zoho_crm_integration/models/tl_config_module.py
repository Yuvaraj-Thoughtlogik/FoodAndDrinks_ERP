import base64
import logging

import psycopg2

from odoo import models, fields, _
from odoo.exceptions import UserError

from odoo.addons.tl_odoo_zoho_integration.utils import key_to_label, parse_datetime_flexibly

_logger = logging.getLogger(__name__)

CRM_API_VERSION = 'v8'
# Zoho accepts at most 50 fields per GET and 100 records per insert/update.
FIELDS_PER_REQUEST = 50
RECORDS_PER_REQUEST = 100


class ZohoConfigModule(models.Model):
    _inherit = 'zoho.config.module'

    module_name_id = fields.Many2one(comodel_name='zoho.import.module.name', string="Module Name ")

    def unlink(self):
        self.module_name_id.imported = False
        return super().unlink()

    # ------------------------------------------------------------------
    # Zoho CRM API
    # ------------------------------------------------------------------
    def _crm_request(self, method, endpoint, **kwargs):
        """Call ``/crm/v8/<endpoint>`` with a valid token (refreshed on 401)."""
        config = self.env['zoho.config']._get_ready_config()
        return config.zoho_request(method, f"crm/{CRM_API_VERSION}/{endpoint}", **kwargs)

    def get_data_from_zoho(self, zoho_module, fields_batch, last_sync=None):
        """Fetch all records of ``zoho_module``, or only those modified since ``last_sync``."""
        field_list = list(fields_batch)
        record_map = {}
        headers = {}
        if last_sync:
            headers['If-Modified-Since'] = fields.Datetime.to_datetime(last_sync).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        for i in range(0, len(field_list), FIELDS_PER_REQUEST):
            params = {'fields': ",".join(field_list[i:i + FIELDS_PER_REQUEST])}
            while True:
                response = self._crm_request('GET', zoho_module, params=params, headers=headers)
                if response.status_code in (204, 304):  # no records / none modified since last_sync
                    break
                if response.status_code != 200:
                    raise UserError(f"Zoho API Error: {response.status_code} - {response.text}")
                response_json = response.json()
                for rec in response_json.get('data', []):
                    if zoho_id := rec.get('id'):
                        record_map.setdefault(zoho_id, {}).update(rec)
                info = response_json.get('info', {})
                next_page_token = info.get('next_page_token') if info.get('more_records') else None
                if not next_page_token:
                    break
                params = dict(params, page_token=next_page_token)
        return list(record_map.values())

    def get_record_detail_from_zoho(self, module_name, record_id):
        """Fetch full record detail (including subforms) from Zoho"""
        response = self._crm_request('GET', f"{module_name}/{record_id}")
        if response.status_code == 204:
            raise UserError(f"Failed to fetch detailed Zoho record: No Record Found {response}")
        if response.status_code != 200:
            raise UserError(f"Failed to fetch detailed Zoho record: {response}")
        return response.json().get('data', [{}])[0]

    def _download_zoho_file(self, file_id):
        response = self._crm_request('GET', 'files', params={'id': file_id})
        if response.status_code == 200:
            return response.content, None
        try:
            error = response.json()
        except ValueError:
            error = response.text
        return None, f"Failed to fetch file {file_id}: {error}"

    def push_records_to_zoho(self, zoho_module, records_batch, method="POST"):
        method = method.upper()
        if method not in ('POST', 'PUT'):
            raise ValueError(f"Invalid method: {method}. Use 'POST' or 'PUT'.")
        merged = {"data": []}
        for i in range(0, len(records_batch), RECORDS_PER_REQUEST):
            response = self._crm_request(method, zoho_module, json={"data": records_batch[i:i + RECORDS_PER_REQUEST]})
            try:
                data = response.json().get("data")
            except ValueError:
                data = None
            if data is None:
                raise UserError(f"Zoho API Error: {response.status_code} - {response.text}")
            merged["data"].extend(data)
        return merged

    def _check_zoho_id_exists(self, zoho_module, zoho_id, cache=None):
        """Whether record ``zoho_id`` exists in ``zoho_module``; ``cache`` (a dict)
        avoids re-checking the same record during one sync run."""
        if not zoho_id:
            return False
        key = (zoho_module, zoho_id)
        if cache is not None and key in cache:
            return cache[key]
        exists = self._crm_request('GET', f"{zoho_module}/{zoho_id}").status_code in (200, 201, 202)
        if cache is not None:
            cache[key] = exists
        return exists

    def multilookup_get_ids(self, zoho_module, rec_id, fields_maps):
        return self._crm_request('GET', f"{zoho_module}/{rec_id}", params={'fields': fields_maps})

    def _get_zoho_records_by_ids(self, zoho_module, zoho_ids, field_names):
        """Fetch ``field_names`` of the given records. Uses the record detail endpoint,
        which is the one returning subform and multi-select lookup values."""
        fields_param = ','.join(field_names)
        records = []
        for zoho_id in dict.fromkeys(filter(None, zoho_ids)):
            response = self.multilookup_get_ids(zoho_module, zoho_id, fields_param)
            if response.status_code == 200 and (data := response.json().get('data')):
                records.append(dict(data[0], id=zoho_id))
        return records

    def delete_existing_multilookup_from_zoho(self, zoho_module, zoho_ids, field_names):
        """Clear the multi-select lookups of ``zoho_ids`` before they are pushed again."""
        if not zoho_ids:
            return
        updates = []
        for record_data in self._get_zoho_records_by_ids(zoho_module, zoho_ids, field_names):
            update_payload = {'id': record_data['id']}
            for field_name in field_names:
                deletions = [{"id": val["id"], "_delete": None}
                             for val in record_data.get(field_name) or [] if val and val.get("id")]
                if deletions:
                    update_payload[field_name] = deletions
            updates.append(update_payload)
        if updates:
            self.push_records_to_zoho(zoho_module, updates, method="PUT")

    def _upload_file_to_zoho(self, filename, file_content):
        try:
            decoded = base64.b64decode(file_content)
        except Exception:
            return None
        response = self._crm_request('POST', 'files', files={'file': (filename, decoded)})
        if response.status_code == 200:
            return response.json()['data'][0].get('details', {}).get('id')
        return None

    # ------------------------------------------------------------------
    # Zoho -> Odoo
    # ------------------------------------------------------------------
    def _prepare_field_value_for_odoo(self, field, field_map, val):
        """Recursively prepares Zoho field value for Odoo field, including nested subforms.

        :return: ``(value | None, error | None)``
        """
        field_type = field.ttype
        rel_model = field.relation

        try:
            # False is what sync_zoho_to_odoo passes for fields absent from the Zoho record
            if val in (None, '', [], {}) or (val is False and field_type != 'boolean'):
                return None, None

            if field_type == 'many2one':
                return self._get_or_create_zoho_related_record(rel_model, val, field_map)

            if field_type == 'many2many':
                if not isinstance(val, list):
                    return None, "Many2many must be provided as a list"
                rel_ids = []
                for item in val:
                    if field_map.name == "Tag":
                        zoho_val = item
                    else:
                        zoho_val = item.get(field_map.name, {}) if isinstance(item, dict) else item
                    if not zoho_val:
                        continue
                    rel_id, error = self._get_or_create_zoho_related_record(rel_model, zoho_val, field_map)
                    if error:
                        return None, error
                    if rel_id:
                        rel_ids.append(rel_id)
                return [(6, 0, rel_ids)], None

            if field_type == 'one2many' and isinstance(val, list):
                sub_vals = [(5, 0, 0)]  # Clear existing one2many records
                sub_errors = []
                if field_map.zoho_id_field_name not in self.env[rel_model]._fields:
                    self._add_custom_field(rel_model, field_map.zoho_id_field_name, 'char', 'Zoho ID')
                for sub_item in val:
                    if not sub_item.get('id'):
                        continue
                    sub_rec = {field_map.zoho_id_field_name: sub_item['id']}
                    item_errors = {}
                    for sub_field in field_map.subform_field_ids:
                        sub_odoo_field = sub_field.odoo_field_id
                        sub_val = sub_item.get(sub_field.name)
                        if sub_val in (None, '', [], {}):
                            continue
                        odoo_val, error = self._prepare_field_value_for_odoo(sub_odoo_field, sub_field, sub_val)
                        if odoo_val is not None:
                            sub_rec[sub_odoo_field.name] = odoo_val
                        if error:
                            item_errors[sub_odoo_field.name] = {
                                'zoho_key': sub_field.name,
                                'error': error,
                                'value': sub_val,
                            }
                    sub_vals.append((0, 0, sub_rec))
                    if item_errors:
                        sub_errors.append(item_errors)
                return sub_vals, sub_errors or None

            if field_type in ('char', 'text', 'html'):
                if isinstance(val, (str, bool)):
                    return val, None
                return None, f"Expected string value, got: {val} ({type(val).__name__})"

            if field_type == 'integer':
                if isinstance(val, (int, float)):
                    return int(val), None
                if isinstance(val, str) and val.strip().isdigit():
                    return int(val.strip()), None
                return None, f"Expected integer-compatible value, got: {val} ({type(val).__name__})"

            if field_type in ('float', 'monetary'):
                if isinstance(val, (int, float)):
                    return float(val), None
                if isinstance(val, str):
                    try:
                        return float(val.strip().replace(',', '')), None
                    except ValueError as e:
                        return None, f"Float conversion error: {e}"
                return None, f"Expected float-compatible value, got: {val} ({type(val).__name__})"

            if field_type == 'boolean':
                if isinstance(val, bool):
                    return val, None
                if isinstance(val, int) and val in (0, 1):
                    return bool(val), None
                if isinstance(val, str):
                    val_lower = val.strip().lower()
                    if val_lower in ('true', 'yes', '1'):
                        return True, None
                    if val_lower in ('false', 'no', '0'):
                        return False, None
                    return None, f"Unrecognized boolean string: {val}"
                return None, f"Expected boolean-compatible value, got: {val} ({type(val).__name__})"

            if field_type in ('date', 'datetime'):
                return parse_datetime_flexibly(val)

            if field_type == 'selection':
                key, error = self.get_selection_key_or_value(field.model, field.name, val, check_as='label')
                return key or None, error or None

            if field_type == 'binary':
                if not (isinstance(val, list) and val):
                    return None, f"Expected File_Data list for binary field, got: {type(val).__name__}"
                file_id = val[0].get('File_Id__s')  # Handle first file for now
                if not file_id:
                    return None, "Missing File_Id__s in File_Data"
                file_data, error = self._download_zoho_file(file_id)
                if file_data:
                    return base64.b64encode(file_data).decode(), None
                return None, error

            return None, f"Unhandled field type '{field_type}' for field '{field.name}'"

        except Exception as e:
            return None, f"[ZOHO] Error preparing value for {field_map.name}: {field_map.odoo_field_name}: {e}"

    def _sync_result(self, status, request, created, updated, errors, unchanged=None):
        return {
            "status": status,
            "odoo_model": self.odoo_model.model or None,
            "zoho_model": self.name,
            "request": request,
            "response": {
                "created": created,
                "updated": updated,
                "errors": errors,
                "unchanged": unchanged or [],
            },
        }

    @staticmethod
    def _db_error(error, zoho_id=None):
        entry = {'zoho_id': zoho_id} if zoho_id else {}
        entry['type'] = type(error).__name__
        entry['error'] = str(error)
        return entry

    def sync_zoho_to_odoo(self, last_sync=None, for_test=None, zoho_ids=None):
        """Pull Zoho records into Odoo: records with a known Zoho ID are updated, others created.

        :param last_sync: only fetch records modified in Zoho since then
        :param zoho_ids: only pull these records (live sync, from Zoho notifications)
        """
        self.ensure_one()
        created, updated, errors, unchanged = [], [], [], []
        request = []

        try:
            # Records written by the pull must not be pushed back by 'Live' schedules.
            odoo_model = self.env[self.odoo_model.model].with_context(zoho_live_skip=True)
            zoho_id_field = self.zoho_id_field
            if zoho_id_field not in odoo_model._fields:
                self._add_custom_field(odoo_model._name, zoho_id_field, 'char', "Zoho ID")

            # === Fetch Records ===
            if for_test and isinstance(for_test, (str, int)):
                record = self.get_record_detail_from_zoho(self.name, for_test)
                if not record:
                    errors.append({
                        'zoho_id': str(for_test),
                        'fetch_error': f"Record with Zoho ID {for_test} not found in module {self.name}"
                    })
                    return self._sync_result("failed", request, created, updated, errors)
                records = [record]
            elif zoho_ids:
                records = []
                for zoho_id in zoho_ids:
                    try:
                        records.append(self.get_record_detail_from_zoho(self.name, zoho_id))
                    except Exception as e:
                        errors.append({'zoho_id': str(zoho_id), 'fetch_error': str(e)})
            else:
                # '_default_field' maps are Odoo-side filters, not Zoho fields. Modified_Time is
                # needed to skip records unchanged since ``last_sync``.
                zoho_fields = self.fields_ids.filtered(lambda fm: not fm.is_default).mapped('name')
                records = self.get_data_from_zoho(self.name, list(dict.fromkeys(zoho_fields + ['Modified_Time'])),
                                                  last_sync)

            # Subform values are only returned by the record detail endpoint.
            needs_detail = not for_test and not zoho_ids and any(
                ftype in ('many2many', 'one2many') for ftype in self.fields_ids.mapped('field_type'))

            # One search for all existing records instead of one per Zoho record
            zoho_ids = [str(rec['id']) for rec in records if rec.get('id')]
            Queue = self.env['zoho.live.queue']
            last_push_times = Queue._last_push_times(self, zoho_ids)
            existing_by_zoho_id = {
                rec[zoho_id_field]: rec
                for rec in odoo_model.search([(zoho_id_field, 'in', zoho_ids)])
            } if zoho_ids else {}

            for rec in records:
                zoho_record_id = str(rec.get('id') or '')
                if not zoho_record_id:
                    continue
                try:
                    existing = existing_by_zoho_id.get(zoho_record_id)
                    modified_time = parse_datetime_flexibly(rec.get('Modified_Time'))[0]
                    if existing and last_sync and modified_time and modified_time < last_sync:
                        unchanged.append({'zoho_id': zoho_record_id, 'status': 'unchanged'})
                        continue
                    if existing and Queue._is_echo(last_push_times.get(zoho_record_id), modified_time):
                        unchanged.append({'zoho_id': zoho_record_id, 'status': 'unchanged',
                                          'reason': 'Only changed in Zoho by our own push'})
                        continue

                    if needs_detail:
                        try:
                            rec = self.get_record_detail_from_zoho(self.name, zoho_record_id)
                        except Exception as e:
                            errors.append({
                                'zoho_id': zoho_record_id,
                                'error': f"Failed to fetch full subform data from Zoho:\n{e}"
                            })
                            continue

                    odoo_vals, rec_request, value_errors = {}, {}, {}
                    for field_map in self.fields_ids:
                        zoho_field = field_map.name.strip()
                        odoo_field = field_map.odoo_field_id
                        val = rec.get(zoho_field, field_map.default_value or False)
                        rec_request[odoo_field.name] = val
                        processed_val, error = self._prepare_field_value_for_odoo(odoo_field, field_map, val)
                        if processed_val is not None:
                            odoo_vals[odoo_field.name] = processed_val
                        if error:
                            value_errors[odoo_field.name] = {'zoho_key': zoho_field, 'error': error, 'value': val}
                    request.append({'zoho_id': zoho_record_id, 'data': rec_request})

                    # === Create or Update ===
                    try:
                        with self.env.cr.savepoint():
                            if existing:
                                existing.write(odoo_vals)
                                updated.append({'zoho_id': zoho_record_id, 'odoo_id': existing.id, 'status': 'success'})
                            else:
                                odoo_vals[zoho_id_field] = zoho_record_id
                                new_rec = odoo_model.create(odoo_vals)
                                existing_by_zoho_id[zoho_record_id] = new_rec
                                created.append({'zoho_id': zoho_record_id, 'odoo_id': new_rec.id, 'status': 'success'})
                    except psycopg2.Error as postgres_e:
                        errors.append({
                            'zoho_id': zoho_record_id,
                            'type': type(postgres_e).__name__,
                            'error': self.format_postgres_error(postgres_e),
                        })
                        continue
                    except Exception as e:
                        errors.append(self._db_error(e, zoho_record_id))
                        continue

                    if value_errors:
                        errors.append({'zoho_id': zoho_record_id, 'type': 'value_errors', 'fields': value_errors})

                except Exception as sync_error:
                    errors.append(self._db_error(sync_error, zoho_record_id))

            status = "success" if created or updated or unchanged else "failed"
            return self._sync_result(status, request, created, updated, errors, unchanged)

        except psycopg2.Error as postgres_e:
            errors.append({'type': type(postgres_e).__name__, 'error': self.format_postgres_error(postgres_e)})
        except Exception as fatal_error:
            errors.append(self._db_error(fatal_error))
        return self._sync_result("failed", request, created, updated, errors)

    # ------------------------------------------------------------------
    # Odoo -> Zoho
    # ------------------------------------------------------------------
    def _prepare_field_value_for_zoho(self, field_map, record, zoho_id=None, exists_cache=None):
        field = field_map.odoo_field_id
        field_type = field.ttype
        odoo_field = field.name
        value = record[odoo_field]

        if value is None:
            return None

        if field_type in ('many2one', 'many2many'):
            rel_model = self.env[field.relation]
            if field_map.is_non_lookup:
                name_field = self._get_name_field(rel_model)
                names = [rel[name_field] or '' for rel in value]
                if field_type == 'many2one':
                    return names[0] if names else ''
                return names
            zoho_id_field = field_map.zoho_id_field_name
            if zoho_id_field not in rel_model._fields:
                return None if field_type == 'many2one' else []
            if field_type == 'many2one':
                related_zoho_id = value[zoho_id_field] if value else None
                if self._check_zoho_id_exists(field_map.zoho_lookup_module, related_zoho_id, exists_cache):
                    return {'id': related_zoho_id}
                return None
            result = []
            for rel in value:
                related_zoho_id = rel[zoho_id_field]
                # Tags are referenced by name/id only; they are not a queryable module.
                if field_map.zoho_lookup_module == 'Tag' or self._check_zoho_id_exists(
                        field_map.zoho_lookup_module, related_zoho_id, exists_cache):
                    result.append({field_map.name: {'id': related_zoho_id}})
            return result

        if field_type == 'one2many':
            line_ids = []
            if zoho_id:
                line_response = self.multilookup_get_ids(self.name, zoho_id, field_map.name)
                try:
                    data = line_response.json().get('data', [])
                except ValueError:
                    _logger.warning("[ZOHO SYNC] Failed to decode JSON response for record %s, field '%s'. "
                                    "Raw response: %s", record.id, field_map.name, line_response.text)
                    data = []
                lines = data[0].get(field_map.name) or [] if data else []
                line_ids = [line['id'] for line in lines if line.get('id')]
            result = []
            for line in value:
                sub_dict = {}
                if zoho_line_id := line[field_map.zoho_id_field_name]:
                    sub_dict['id'] = zoho_line_id
                    if zoho_line_id in line_ids:
                        line_ids.remove(zoho_line_id)
                for subfield in field_map.subform_field_ids:
                    sub_dict[subfield.name] = self._prepare_field_value_for_zoho(
                        subfield, line, exists_cache=exists_cache)
                result.append(sub_dict)
            # Lines that no longer exist in Odoo are removed from Zoho
            result.extend({'id': line_id, '_delete': None} for line_id in line_ids)
            return result

        if field_type in ('char', 'text', 'html'):
            return value or None
        if field_type == 'boolean':
            return bool(value)
        if field_type in ('float', 'monetary', 'integer'):
            return value if value is not False else None
        if field_type in ('date', 'datetime'):
            return value.isoformat() if value else None
        if field_type == 'selection':
            return key_to_label(value) if value else None
        if field_type == 'binary':
            if value:
                filename_field = f'{odoo_field}_filename'
                file_name = (record[filename_field] if filename_field in record._fields else None) or 'file'
                if file_id := self._upload_file_to_zoho(file_name, value):
                    return [{'File_Id__s': file_id}]
            return None
        return None

    def _check_push_response(self, records, response_data, zoho_id_field, created_or_updated, errors, is_create):
        # Zoho answers in the same order as the pushed records
        for rec, res in zip(records, response_data):
            zoho_id = res.get('details', {}).get('id')
            if res.get('status') == 'success':
                if is_create:
                    # Own savepoint: a failed write (e.g. the record is being edited concurrently)
                    # must not abort the whole sync transaction.
                    try:
                        with self.env.cr.savepoint():
                            rec.write({zoho_id_field: zoho_id or ""})
                    except Exception as e:
                        _logger.warning("[ZOHO SYNC] Created %s in Zoho but could not store its Zoho ID on "
                                        "%s: %s", zoho_id, rec, e)
                        errors.append({"odoo_id": rec.id, "zoho_id": zoho_id, "status": "failed",
                                       "type": type(e).__name__,
                                       "error": f"Created in Zoho as {zoho_id} but the Zoho ID could not be "
                                                f"stored in Odoo: {e}"})
                        continue
                created_or_updated.append({"odoo_id": rec.id, "zoho_id": zoho_id, "status": "success"})
            else:
                errors.append({"odoo_id": rec.id, "zoho_id": zoho_id, "status": "failed", "error": res})

    def _get_default_domain(self):
        """Odoo-side filter of the records belonging to this module ('_default_field' maps)."""
        return [
            (field_map.odoo_field_name, '=',
             field_map.default_value if field_map.field_type != 'boolean'
             else (field_map.default_value or "").lower() == "true")
            for field_map in self.fields_ids if field_map.is_default
        ]

    def sync_odoo_to_zoho(self, last_sync=None, for_test=None, record_ids=None):
        """Push Odoo records to Zoho: records with an existing Zoho ID are updated, others created.

        :param record_ids: only push these records, even if unchanged since ``last_sync`` (live sync)
        """
        self.ensure_one()
        create_batch, update_batch = {}, {}
        created, updated, errors, unchanged = [], [], [], []
        request_msg = []

        if not self.odoo_model:
            errors.append(f"Odoo model not set for module {self.name}")
            return self._sync_result('failed', {}, [], [], errors)

        # The Zoho ID write-back must not re-trigger 'Live' schedules.
        odoo_model = self.env[self.odoo_model.model].with_context(zoho_live_skip=True)
        zoho_id_field = self.zoho_id_field
        if zoho_id_field not in odoo_model._fields:
            self._add_custom_field(odoo_model._name, zoho_id_field, 'char', 'Zoho ID')

        if record_ids:
            domain = [('id', 'in', record_ids)]
        else:
            domain = [('id', '=', for_test)] if for_test and isinstance(for_test, int) else []
        domain += self._get_default_domain()
        records = odoo_model.search(domain)
        if not records:
            errors.append(f"No records found to sync {odoo_model._name}")
            return self._sync_result('failed', {}, [], [], errors)

        lookup_maps = self.fields_ids.filtered(lambda fm: not fm.is_non_lookup)
        many2many_fields = lookup_maps.filtered(lambda fm: fm.field_type == 'many2many').mapped('name')
        one2many_fields = lookup_maps.filtered(lambda fm: fm.field_type == 'one2many')
        exists_cache = {}
        zoho_ids = []
        for rec in records:
            rec_zoho_id = rec[zoho_id_field]
            try:
                is_update = self._check_zoho_id_exists(self.name, rec_zoho_id, exists_cache)
                # Skip before preparing values: that step uploads files and queries Zoho.
                if is_update and not record_ids and rec.write_date and last_sync and rec.write_date < last_sync:
                    unchanged.append({'odoo_id': rec.id, 'zoho_id': rec_zoho_id})
                    continue

                zoho_data, request_data = {}, {}
                for field_map in self.fields_ids:
                    zoho_val = self._prepare_field_value_for_zoho(
                        field_map, rec, zoho_id=rec_zoho_id if is_update else None, exists_cache=exists_cache)
                    request_data[field_map.name] = zoho_val
                    if zoho_val is not None:
                        zoho_data[field_map.name] = zoho_val
                request_msg.append({'odoo_id': rec.id, 'data': request_data})

                if is_update:
                    zoho_ids.append(rec_zoho_id)
                    zoho_data["id"] = rec_zoho_id
                    update_batch[rec] = zoho_data
                else:
                    create_batch[rec] = zoho_data

            except Exception as e:
                _logger.warning("[ZOHO SYNC] Skipping record ID %s due to error: %s", rec.id, e)
                errors.append({"record_id": rec.id, 'type': type(e).__name__, "error": str(e)})
                request_msg.append({'odoo_id': rec.id, 'error': str(e)})

        if many2many_fields:
            self.delete_existing_multilookup_from_zoho(self.name, zoho_ids, many2many_fields)

        for batch, method, target, is_create in (
                (create_batch, 'POST', created, True),
                (update_batch, 'PUT', updated, False)):
            if not batch:
                continue
            _logger.info("[ZOHO SYNC] %s %s records in Zoho", method, len(batch))
            try:
                response = self.push_records_to_zoho(self.name, list(batch.values()), method=method)
                self._check_push_response(list(batch), response['data'], zoho_id_field, target, errors, is_create)
            except Exception as e:
                errors.append({"status": "failed", 'type': type(e).__name__, "error": str(e)})

        # Store the Zoho subform line ids on the Odoo lines
        if one2many_fields:
            zoho_fields = one2many_fields.mapped('name')
            synced = {batch["zoho_id"]: batch["odoo_id"] for batch in created + updated if batch["zoho_id"]}
            for record_data in self._get_zoho_records_by_ids(self.name, list(synced), zoho_fields):
                rec = odoo_model.browse(synced.get(record_data.get('id')))
                if not rec:
                    continue
                for one2many in one2many_fields:
                    zoho_lines = [line.get("id") for line in record_data.get(one2many.name) or []]
                    try:
                        with self.env.cr.savepoint():
                            for row_index, subform in enumerate(rec[one2many.odoo_field_name]):
                                subform.write({
                                    one2many.zoho_id_field_name:
                                        zoho_lines[row_index] if row_index < len(zoho_lines) else ""
                                })
                    except Exception as e:
                        _logger.warning("[ZOHO SYNC] Could not store Zoho subform ids on %s: %s", rec, e)
                        errors.append({"odoo_id": rec.id, 'type': type(e).__name__,
                                       "error": f"Zoho subform line ids could not be stored: {e}"})

        if not record_ids and not for_test:
            # Live pushes are remembered by the queue itself.
            self.env['zoho.live.queue']._remember_pushes(self, created + updated)

        status = "success" if created or updated or unchanged else 'failed'
        return self._sync_result(status, request_msg, created, updated, errors, unchanged)

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    def _sync_zoho_notes_for_record(self, odoo_record, zoho_module, zoho_record_id):
        """Sync Zoho Notes for a specific record"""
        if 'x_crm_zoho_id' not in self.env['mail.message']._fields:
            self._add_custom_field('mail.message', 'x_crm_zoho_id', 'char', 'Zoho Note ID')

        response = self._crm_request('GET', f"{zoho_module}/{zoho_record_id}/Notes")
        if response.status_code != 200:
            return

        notes = response.json().get("data", [])
        known_ids = set(self.env['mail.message'].search([
            ('model', '=', odoo_record._name),
            ('res_id', '=', odoo_record.id),
            ('x_crm_zoho_id', 'in', [note.get('id') for note in notes]),
        ]).mapped('x_crm_zoho_id'))
        for note in notes:
            if note.get('id') in known_ids:
                continue
            message = odoo_record.message_post(
                body=note.get('Note_Content') or '(No content)',
                subject=note.get('Note_Title') or 'Zoho Note',
                message_type='comment',
            )
            message.sudo().write({'x_crm_zoho_id': note.get('id')})
