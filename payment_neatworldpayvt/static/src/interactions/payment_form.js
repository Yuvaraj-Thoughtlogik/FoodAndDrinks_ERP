/** @odoo-module */

import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';

import { PaymentForm } from '@payment/interactions/payment_form';

patch(PaymentForm.prototype, {

    /**
     * Open the inline form of the selected payment option, if any.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {Event} ev
     * @return {void}
     */
    async _selectPaymentOption(ev) {
        await super._selectPaymentOption(...arguments);
    },

    /**
     * Prepare the inline form of Worldpay Virtual Terminal for direct payment.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {number} providerId - The id of the selected payment option's provider.
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The online payment flow of the selected payment option.
     * @return {void}
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'neatworldpayvt') {
            super._prepareInlineForm(...arguments);
            return;
        }
        
        if (flow === 'token') {
            return;
        }
        this._setPaymentFlow('direct');
    },

    // #=== PAYMENT FLOW ===#

    /**
     * Process direct payment flow for Worldpay Virtual Terminal.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'neatworldpayvt') {
            super._processDirectFlow(...arguments);
            return;
        }
        
        if(!processingValues.transaction_key || !processingValues.checkout_id) {
            alert("Worldpay integration is not active. Please update the activation code and checkout ID.");
            return;
        }
        
        this.env.bus.trigger('ui', 'unblock');
        const popup = document.querySelector('#neatworldpayvt_popup');
        if (popup) {
            popup.style.display = 'block';
            this._populateVirtualTerminalContainer(processingValues);
        }
    },

    /**
     * Process token payment flow for Worldpay Virtual Terminal.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
    async _processTokenFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'neatworldpayvt') {
            super._processTokenFlow(...arguments);
            return;
        }
        
        if(!processingValues.transaction_key || !processingValues.checkout_id) {
            alert("Worldpay integration is not active. Please update the activation code and checkout ID.");
            return;
        }
        
        this.env.bus.trigger('ui', 'unblock');
        const popup = document.querySelector('#neatworldpayvt_popup');
        if (popup) {
            popup.style.display = 'block';
            this._populateVirtualTerminalContainer(processingValues);
        }
    },

    /**
     * Populate the virtual terminal container with payment form.
     *
     * @private
     * @param {object} processingValues - The processing values of the transaction
     * @return {undefined}
     */
    _populateVirtualTerminalContainer: function (processingValues) {
        const container = document.querySelector('#neatworldpayvt-container');
        if (!container) return;

        const disclaimerText = _t("This payment channel is strictly for internal employee use. It must never be presented to customers and is not approved for ecommerce transactions.");
        const transactionReference = processingValues.transaction_reference || '';
        const transactionKey = processingValues.transaction_key || '';
        const checkoutId = processingValues.checkout_id || '';
        const worldpayUrl = processingValues.worldpay_url || 'https://try.access.worldpay.com';
        const billingAddress = processingValues.billing_address || {};
        const countries = processingValues.countries || [];
        const savedPaymentTokens = processingValues.saved_payment_tokens || [];

        if (!checkoutId) {
            container.innerHTML = `
                <div style="text-align: center; padding: 20px;">
                    <h3 style="margin-bottom: 20px; color: #dc3545;">Configuration Error</h3>
                    <p style="color: #666;">Checkout ID is missing. Please contact support.</p>
                    <button type="button" onclick="closeVirtualTerminalPopup()" 
                            style="background: #6c757d; color: white; border: none; border-radius: 4px; padding: 10px 20px; cursor: pointer; font-size: 14px; margin-top: 20px;">
                        Close
                    </button>
                </div>
            `;
            return;
        }
        
        container.innerHTML = `
            <style>
                .checkout .label {
                    font-size: 13px;
                    font-weight: 500;
                    color: #495057;
                    margin-bottom: 8px;
                    display: block;
                }
                .checkout .label .type {
                    color: green;
                    font-weight: 400;
                    margin-left: 8px;
                }
                .checkout.visa .label .type:before {
                    content: "(visa)";
                }
                .checkout.mastercard .label .type:before {
                    content: "(master card)";
                }
                .checkout.amex .label .type:before {
                    content: "(american express)";
                }
                .checkout .field {
                    height: 40px;
                    border-bottom: 1px solid lightgray;
                    margin-bottom: 0;
                }
                .checkout .field#card-pan {
                    margin-bottom: 30px;
                }
                .checkout .field#card-expiry,
                .checkout .field#card-cvv {
                    min-width: 120px;
                }
                .checkout .field#card-expiry input,
                .checkout .field#card-cvv input {
                    font-size: 18px;
                    font-weight: 600;
                    letter-spacing: 2px;
                    width: 100%;
                }
                .checkout .field.is-onfocus {
                    border-color: black;
                }
                .checkout .field.is-empty {
                    border-color: orange;
                }
                .checkout .field.is-invalid {
                    border-color: red;
                }
                .checkout .field.is-valid {
                    border-color: green;
                }
                .checkout .col-2 {
                    display: flex;
                }
                .checkout .col-2 .col {
                    flex: 1;
                }
                .checkout .col-2 .col:first-child {
                    margin-right: 15px;
                }
                .checkout .col-2 .col:last-child {
                    margin-left: 15px;
                }
                .form-group {
                    margin-bottom: 16px;
                }
                .form-group label {
                    display: block;
                    font-size: 13px;
                    font-weight: 500;
                    color: #495057;
                    margin-bottom: 6px;
                }
                .form-group input[type="text"],
                .form-group select {
                    width: 100%;
                    padding: 8px 12px;
                    border: 1px solid #ced4da;
                    border-radius: 4px;
                    font-size: 14px;
                    color: #495057;
                    background-color: #fff;
                    transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
                }
                .form-group input[type="text"]:focus,
                .form-group select:focus {
                    outline: 0;
                    border-color: #80bdff;
                    box-shadow: 0 0 0 0.2rem rgba(0, 123, 255, 0.25);
                }
                .form-group input[type="text"].error,
                .form-group select.error {
                    border-color: #dc3545;
                }
                .saved-card-wrap {
                    border: 1px solid #dee2e6;
                    border-radius: 5px;
                    padding: 12px;
                    margin-bottom: 18px;
                    background: #f8f9fa;
                }
                .saved-card-wrap label {
                    display: block;
                    font-size: 13px;
                    font-weight: 500;
                    color: #495057;
                    margin-bottom: 6px;
                }
                .payment-method-option {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 14px;
                    color: #495057;
                    margin: 8px 0;
                    cursor: pointer;
                }
                .payment-method-option input {
                    margin: 0;
                }
                .save-card-wrap {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 13px;
                    color: #495057;
                    margin: 4px 0 16px;
                }
                .new-card-fields.hidden {
                    display: none;
                }
                .submit {
                    background: #007bff;
                    cursor: pointer;
                    width: 100%;
                    margin-top: 20px;
                    color: white;
                    outline: 0;
                    font-size: 14px;
                    border: 1px solid #007bff;
                    border-radius: 4px;
                    font-weight: 500;
                    padding: 10px 16px;
                    transition: background-color 0.15s ease-in-out, border-color 0.15s ease-in-out;
                }
                .submit:hover {
                    background: #0069d9;
                    border-color: #0062cc;
                }
                .submit:disabled {
                    background: #6c757d;
                    border-color: #6c757d;
                    cursor: not-allowed;
                    opacity: 0.65;
                }
                .checkout.is-valid .submit {
                    background: #28a745;
                    border-color: #28a745;
                }
                .checkout.is-valid .submit:hover {
                    background: #218838;
                    border-color: #1e7e34;
                }
                .button-group {
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                    margin-top: 20px;
                }
                .clear {
                    background: #6c757d;
                    cursor: pointer;
                    width: 100%;
                    color: white;
                    outline: 0;
                    font-size: 14px;
                    border: 1px solid #6c757d;
                    border-radius: 4px;
                    font-weight: 500;
                    padding: 10px 16px;
                    transition: background-color 0.15s ease-in-out, border-color 0.15s ease-in-out;
                }
                .clear:hover {
                    background: #5a6268;
                    border-color: #545b62;
                }
                .clear:disabled {
                    background: #6c757d;
                    border-color: #6c757d;
                    cursor: not-allowed;
                    opacity: 0.65;
                }
                .cancel {
                    background: #dc3545;
                    cursor: pointer;
                    width: 100%;
                    color: white;
                    outline: 0;
                    font-size: 14px;
                    border: 1px solid #dc3545;
                    border-radius: 4px;
                    font-weight: 500;
                    padding: 10px 16px;
                    transition: background-color 0.15s ease-in-out, border-color 0.15s ease-in-out;
                }
                .cancel:hover {
                    background: #c82333;
                    border-color: #bd2130;
                }
                .cancel:disabled {
                    background: #6c757d;
                    border-color: #6c757d;
                    cursor: not-allowed;
                    opacity: 0.65;
                }
                .error-message {
                    color: #dc3545;
                    font-size: 12px;
                    margin-top: 4px;
                    display: none;
                }
                .error-message.show {
                    display: block;
                }
                .success-message {
                    color: #28a745;
                    font-size: 14px;
                    margin-top: 15px;
                    text-align: center;
                    display: none;
                    padding: 12px;
                    background-color: #d4edda;
                    border: 1px solid #c3e6cb;
                    border-radius: 4px;
                }
                .success-message.show {
                    display: block;
                }
                .success-message[style*="color: #dc3545"] {
                    background-color: #f8d7da;
                    border-color: #f5c6cb;
                    color: #dc3545;
                }
                .disclaimer {
                    font-size: 14px;
                    background-color: #fff3cd;
                    border: 1px solid #ffeeba;
                    color: #856404;
                    border-radius: 5px;
                    padding: 12px 15px;
                    margin-bottom: 20px;
                    line-height: 1.4;
                }
                .checkout.hide-fields .label,
                .checkout.hide-fields .field,
                .checkout.hide-fields .form-group,
                .checkout.hide-fields .button-group {
                    display: none;
                }
                .checkout.hide-fields .success-message,
                .checkout.hide-fields #form-error {
                    display: block;
                    text-align: center;
                    margin-top: 30px;
                    font-size: 16px;
                }
            </style>
            <div style="padding: 20px; max-width: 500px; margin: 0 auto;">
                <div style="text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #e9ecef;">
                    <h1 style="margin: 0 0 10px 0; font-size: 24px; font-weight: 600; color: #33475b;">Virtual Terminal Payment</h1>
                </div>
                <p class="disclaimer">${disclaimerText}</p>
                
                <form class="checkout" id="card-form">
                    <div class="saved-card-wrap" id="savedCardWrap">
                        <div style="font-size: 13px; font-weight: 500; color: #495057; margin-bottom: 6px;">Payment method</div>
                        <label class="payment-method-option">
                            <input type="radio" name="selectedPaymentTokenId" value="" checked>
                            <span>Use a new card</span>
                        </label>
                        <div id="savedPaymentTokenOptions"></div>
                    </div>
                    <div class="new-card-fields" id="newCardFields">
                        <div class="label">Card number <span class="type"></span></div>
                        <section id="card-pan" class="field"></section>
                        <section class="col-2">
                            <section class="col">
                                <div class="label">Expiry date</div>
                                <section id="card-expiry" class="field"></section>
                            </section>
                            <section class="col">
                                <div class="label">CVV</div>
                                <section id="card-cvv" class="field"></section>
                            </section>
                        </section>
                        
                        <div class="form-group">
                            <label for="cardholderName">Cardholder Name</label>
                            <input type="text" id="cardholderName" name="cardholderName" required>
                            <div class="error-message" id="cardholderName-error"></div>
                        </div>
                        
                        <div class="form-group">
                            <label for="address">Address</label>
                            <input type="text" id="address" name="address" value="${billingAddress.addressLine || ''}" required>
                            <div class="error-message" id="address-error"></div>
                        </div>
                        
                        <div class="form-group">
                            <label for="address2">Address 2</label>
                            <input type="text" id="address2" name="address2" value="${billingAddress.addressLine2 || ''}">
                            <div class="error-message" id="address2-error"></div>
                        </div>
                        
                        <div class="form-group">
                            <label for="address3">Address 3</label>
                            <input type="text" id="address3" name="address3" value="${billingAddress.address3 || ''}">
                            <div class="error-message" id="address3-error"></div>
                        </div>
                        
                        <div class="form-group">
                            <label for="city">City</label>
                            <input type="text" id="city" name="city" value="${billingAddress.city || ''}" required>
                            <div class="error-message" id="city-error"></div>
                        </div>
                        
                        <div class="form-group">
                            <label for="state">State</label>
                            <input type="text" id="state" name="state" value="${billingAddress.state || ''}">
                            <div class="error-message" id="state-error"></div>
                        </div>
                        
                        <div class="form-group">
                            <label for="country">Country</label>
                            <select id="country" name="country" required>
                                <option value="">Select a country...</option>
                            </select>
                            <div class="error-message" id="country-error"></div>
                        </div>
                        
                        <div class="form-group">
                            <label for="postcode">Postcode</label>
                            <input type="text" id="postcode" name="postcode" value="${billingAddress.postalCode || ''}" required>
                            <div class="error-message" id="postcode-error"></div>
                        </div>
                        <label class="save-card-wrap">
                            <input type="checkbox" id="saveCardDetails" name="saveCardDetails"/>
                            Save this card for future virtual terminal payments
                        </label>
                    </div>
                    
                    <div class="button-group">
                        <button class="submit" type="submit">Charge Customer</button>
                        <button class="clear" type="button" id="clear">Clear</button>
                        <button class="cancel" type="button" id="cancel">Cancel</button>
                    </div>
                    <div class="error-message" id="form-error"></div>
                    <div class="success-message" id="success-message">Payment processed successfully!</div>
                </form>
            </div>
        `;

        // Store values for later use
        window._neatworldpayvt_data = {
            transactionReference: transactionReference,
            transactionKey: transactionKey,
            checkoutId: checkoutId,
            worldpayUrl: worldpayUrl,
            countries: countries,
            countryCode: billingAddress.country || '',
            billingAddress: billingAddress,
            savedPaymentTokens: savedPaymentTokens
        };

        // Load Worldpay checkout.js and initialize
        this._loadWorldpayCheckout(checkoutId, worldpayUrl, countries, billingAddress.country || '', savedPaymentTokens);
    },

    /**
     * Toggle HTML5 required on billing fields (hidden fields must not stay required).
     *
     * @private
     * @param {boolean} required
     * @return {undefined}
     */
    _setBillingFieldsRequired: function (required) {
        ['cardholderName', 'address', 'city', 'country', 'postcode'].forEach(function (fieldId) {
            const field = document.getElementById(fieldId);
            if (!field) {
                return;
            }
            if (required) {
                field.setAttribute('required', 'required');
            } else {
                field.removeAttribute('required');
            }
        });
    },

    /**
     * Show or hide new-card fields based on saved-card selection.
     *
     * @private
     * @return {undefined}
     */
    _toggleNewCardFields: function () {
        const selectedTokenInput = document.querySelector('input[name="selectedPaymentTokenId"]:checked');
        const useSavedCard = Boolean(selectedTokenInput && selectedTokenInput.value);
        const newCardFields = document.getElementById('newCardFields');
        if (newCardFields) {
            newCardFields.classList.toggle('hidden', useSavedCard);
        }
        this._setBillingFieldsRequired(!useSavedCard);
    },

    /**
     * Load Worldpay checkout.js and initialize the form.
     *
     * @private
     * @param {string} checkoutId - The Worldpay checkout ID
     * @param {string} worldpayUrl - The Worldpay base URL
     * @param {Array} countries - Array of country objects
     * @param {string} countryCode - Default country code
     * @param {Array} savedPaymentTokens - Saved VT token options
     * @return {undefined}
     */
    _loadWorldpayCheckout: function (checkoutId, worldpayUrl, countries, countryCode, savedPaymentTokens) {
        const self = this;
        
        // Populate country dropdown
        const countrySelect = document.getElementById('country');
        if (countrySelect && countries && Array.isArray(countries)) {
            countries.forEach(function(country) {
                const option = document.createElement('option');
                option.value = country.code || '';
                option.textContent = country.name || '';
                if (country.code === countryCode) {
                    option.selected = true;
                }
                countrySelect.appendChild(option);
            });
        }
        const savedTokenOptions = document.getElementById('savedPaymentTokenOptions');
        const newCardFields = document.getElementById('newCardFields');
        if (savedTokenOptions && savedPaymentTokens && savedPaymentTokens.length) {
            savedPaymentTokens.forEach(function(token) {
                const label = document.createElement('label');
                label.className = 'payment-method-option';
                const input = document.createElement('input');
                input.type = 'radio';
                input.name = 'selectedPaymentTokenId';
                input.value = token.payment_token_id || '';
                const text = document.createElement('span');
                text.textContent = token.label || 'Saved card';
                label.appendChild(input);
                label.appendChild(text);
                savedTokenOptions.appendChild(label);
            });
        }
        document.querySelectorAll('input[name="selectedPaymentTokenId"]').forEach(function (input) {
            input.addEventListener('change', function () {
                self._toggleNewCardFields();
            });
        });
        this._toggleNewCardFields();

        // Load Worldpay checkout.js script if not already loaded
        if (!window.Worldpay || !window.Worldpay.checkout) {
            const script = document.createElement('script');
            script.src = `${worldpayUrl}/access-checkout/v2/checkout.js`;
            script.onload = function() {
                self._initializeWorldpayCheckout(checkoutId);
            };
            script.onerror = function() {
                const errorEl = document.getElementById('form-error');
                if (errorEl) {
                    errorEl.textContent = 'Failed to load payment form. Please refresh the page.';
                    errorEl.classList.add('show');
                }
            };
            document.head.appendChild(script);
        } else {
            this._initializeWorldpayCheckout(checkoutId);
        }
    },

    /**
     * Initialize Worldpay checkout form.
     *
     * @private
     * @param {string} checkoutId - The Worldpay checkout ID
     * @return {undefined}
     */
    _initializeWorldpayCheckout: function (checkoutId) {
        const self = this;
        const form = document.getElementById('card-form');
        if (!form) return;

        Worldpay.checkout.init(
            {
                id: checkoutId,
                form: '#card-form',
                fields: {
                    pan: {
                        selector: '#card-pan',
                        placeholder: '4444 3333 2222 1111'
                    },
                    expiry: {
                        selector: '#card-expiry',
                        placeholder: 'MM/YY'
                    },
                    cvv: {
                        selector: '#card-cvv',
                        placeholder: '123'
                    }
                },
                styles: {
                    'input': {
                        'color': '#33475b',
                        'font-weight': '600',
                        'font-size': '16px',
                        'letter-spacing': '1px'
                    },
                    'input#pan': {
                        'font-size': '18px'
                    },
                    'input.is-valid': {
                        'color': '#28a745'
                    },
                    'input.is-invalid': {
                        'color': '#dc3545'
                    },
                    'input.is-onfocus': {
                        'color': '#33475b'
                    }
                },
                acceptedCardBrands: ['amex', 'diners', 'discover', 'jcb', 'maestro', 'mastercard', 'visa'],
                enablePanFormatting: true
            },
            function (error, checkout) {
                if (error) {
                    console.error(error);
                    document.getElementById('form-error').textContent = 'Failed to initialize payment form. Please refresh the page.';
                    document.getElementById('form-error').classList.add('show');
                    return;
                }
                
                // Setup form validation and submission
                self._setupFormValidation(checkout);
            }
        );
    },

    /**
     * Setup form validation and submission handling.
     *
     * @private
     * @param {object} checkout - The Worldpay checkout instance
     * @return {undefined}
     */
    _setupFormValidation: function (checkout) {
        const self = this;
        const form = document.getElementById('card-form');
        const clearBtn = document.getElementById('clear');
        const data = window._neatworldpayvt_data;

        // Validation functions
        const validators = {
            cardholderName: function(value) {
                const trimmed = (value || '').trim();
                if (trimmed.length < 1) return 'Cardholder name is required';
                if (trimmed.length > 255) return 'Cardholder name must be 255 characters or less';
                return '';
            },
            address: function(value) {
                const trimmed = (value || '').trim();
                if (trimmed.length < 1) return 'Address is required';
                if (trimmed.length > 80) return 'Address must be 80 characters or less';
                return '';
            },
            address2: function(value) {
                const trimmed = (value || '').trim();
                if (trimmed.length > 80) return 'Address line 2 must be 80 characters or less';
                return '';
            },
            address3: function(value) {
                const trimmed = (value || '').trim();
                if (trimmed.length > 80) return 'Address line 3 must be 80 characters or less';
                return '';
            },
            city: function(value) {
                const trimmed = (value || '').trim();
                if (trimmed.length < 1) return 'City is required';
                if (trimmed.length > 50) return 'City must be 50 characters or less';
                return '';
            },
            state: function(value) {
                const trimmed = (value || '').trim();
                if (trimmed.length > 30) return 'State must be 30 characters or less';
                return '';
            },
            postcode: function(value) {
                const trimmed = (value || '').trim();
                if (trimmed.length < 1) return 'Postcode is required';
                if (trimmed.length > 15) return 'Postcode must be 15 characters or less';
                return '';
            },
            country: function(value) {
                if (!value) return 'Country is required';
                return '';
            }
        };

        function showFieldError(fieldId, errorMessage) {
            const field = document.getElementById(fieldId);
            const errorElement = document.getElementById(fieldId + '-error');
            if (errorMessage) {
                errorElement.textContent = errorMessage;
                errorElement.classList.add('show');
                field.classList.add('error');
            } else {
                errorElement.textContent = '';
                errorElement.classList.remove('show');
                field.classList.remove('error');
            }
        }

        // Add real-time validation
        Object.keys(validators).forEach(function(fieldId) {
            const field = document.getElementById(fieldId);
            if (field) {
                field.addEventListener('input', function() {
                    const error = validators[fieldId](this.value);
                    showFieldError(fieldId, error);
                });
            }
        });

        // Form submission
        form.addEventListener('submit', function(event) {
            event.preventDefault();
            self._toggleNewCardFields();

            const selectedTokenInput = document.querySelector('input[name="selectedPaymentTokenId"]:checked');
            const selectedTokenId = selectedTokenInput ? selectedTokenInput.value : '';

            let hasErrors = false;
            if (!selectedTokenId) {
                Object.keys(validators).forEach(function(fieldId) {
                    const field = document.getElementById(fieldId);
                    if (field) {
                        const error = validators[fieldId](field.value);
                        if (error) {
                            showFieldError(fieldId, error);
                            hasErrors = true;
                        }
                    }
                });
            }

            if (hasErrors) {
                return;
            }

            // Disable submit, clear, and cancel buttons
            const submitButton = form.querySelector('.submit');
            const clearButton = document.getElementById('clear');
            const cancelButton = document.getElementById('cancel');
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
            if (clearButton) clearButton.disabled = true;
            if (cancelButton) cancelButton.disabled = true;

            function submitPayment(sessionState) {
                // Submit payment data to backend via form POST
                const submitForm = document.createElement('form');
                submitForm.method = 'POST';
                submitForm.action = '/neatworldpayvt/process-payment';
                
                const fields = {
                    transaction_reference: data.transactionReference,
                    transaction_key: data.transactionKey,
                    sessionState: sessionState || '',
                    cardholderName: document.getElementById('cardholderName').value.trim(),
                    address: document.getElementById('address').value.trim(),
                    address2: document.getElementById('address2').value.trim(),
                    address3: document.getElementById('address3').value.trim(),
                    city: document.getElementById('city').value.trim(),
                    state: document.getElementById('state').value.trim(),
                    country: document.getElementById('country').value,
                    postcode: document.getElementById('postcode').value.trim(),
                    selected_payment_token_id: selectedTokenId,
                    save_card_details: document.getElementById('saveCardDetails').checked ? '1' : ''
                };
                
                Object.keys(fields).forEach(function(key) {
                    const input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = key;
                    input.value = fields[key];
                    submitForm.appendChild(input);
                });
                
                document.body.appendChild(submitForm);
                submitButton.disabled = true;
                if (clearButton) clearButton.disabled = true;
                if (cancelButton) cancelButton.disabled = true;
                submitForm.submit();
            }

            if (selectedTokenId) {
                submitPayment('');
                return;
            }

            // Generate session state
            checkout.generateSessionState(function(error, sessionState) {
                if (error) {
                    console.error(error);
                    document.getElementById('form-error').textContent = 'Failed to process payment. Please try again.';
                    document.getElementById('form-error').classList.add('show');
                    submitButton.disabled = false;
                    submitButton.textContent = 'Charge Customer';
                    if (clearButton) clearButton.disabled = false;
                    if (cancelButton) cancelButton.disabled = false;
                    return;
                }
                submitPayment(sessionState);
            });
        });

        // Clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', function(event) {
                event.preventDefault();
                checkout.clearForm(function() {
                    document.getElementById('cardholderName').value = '';
                    const billingAddress = data.billingAddress || {};
                    document.getElementById('address').value = billingAddress.addressLine || '';
                    document.getElementById('address2').value = billingAddress.addressLine2 || '';
                    document.getElementById('address3').value = '';
                    document.getElementById('city').value = billingAddress.city || '';
                    document.getElementById('state').value = billingAddress.state || '';
                    document.getElementById('country').value = data.countryCode || '';
                    document.getElementById('postcode').value = billingAddress.postalCode || '';
                    const newCardRadio = document.querySelector('input[name="selectedPaymentTokenId"][value=""]');
                    const newCardFields = document.getElementById('newCardFields');
                    if (newCardRadio) {
                        newCardRadio.checked = true;
                    }
                    if (newCardFields) {
                        newCardFields.classList.remove('hidden');
                    }
                    self._toggleNewCardFields();
                    const saveCardDetails = document.getElementById('saveCardDetails');
                    if (saveCardDetails) {
                        saveCardDetails.checked = false;
                    }
                    
                    document.querySelectorAll('.error-message').forEach(function(el) {
                        el.classList.remove('show');
                    });
                    document.querySelectorAll('input, select').forEach(function(el) {
                        el.classList.remove('error');
                    });
                });
            });
        }
        
        // Cancel button
        const cancelBtn = document.getElementById('cancel');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', function(event) {
                event.preventDefault();
                self.closeVirtualTerminalPopup();
            });
        }
    },

    /**
     * Close virtual terminal popup.
     */
    closeVirtualTerminalPopup: function() {
        const popup = document.querySelector('#neatworldpayvt_popup');
        if (popup) {
            popup.style.display = 'none';
        }
    },

});

// Add close function to global scope
window.closeVirtualTerminalPopup = function() {
    const popup = document.querySelector('#neatworldpayvt_popup');
    if (popup) {
        popup.style.display = 'none';
    }
};
