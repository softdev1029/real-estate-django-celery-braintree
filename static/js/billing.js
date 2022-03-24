$(function() {
    var hostedFields = null;
    var sendForm = function(e) {
        $("#signup-animation-btn").show();
        $("#signup-btn").hide();
        $("#alert-invalid-cc-info").hide();
        $("#submit-btn").hide();
        $("#submit-btn-animated").show();
        $("#cancel-btn").attr('disabled', '');
        e.preventDefault();
        hostedFields.tokenize(function(err, payload) {
            if (err) {
                $("#signup-animation-btn").hide();
                $("#signup-btn").show();
                $("#alert-invalid-cc-info").show();
                $("#submit-btn").show();
                $("#submit-btn-animated").hide();
                $("#cancel-btn").removeAttr("disabled");
                return;
            }
            $('#id_payment_method_nonce').val(payload.nonce);
            $('#signupForm').off('submit', sendForm);
            $('#signupForm').submit();
        });
    };
    $('#signupForm').on('submit', sendForm);

    braintree.client.create({authorization: bt_auth}, function(err, client) {
        if (err) {
            console.error(err);
            return;
        }

        var options = {
            client: client,
            styles: {
                input: {
                    'font-size': '14px',
                    color: '#676a6c',
                }
            },
            fields: {
                number: {
                    selector: '#id_credit_card_number',
                    placeholder: '•••• •••• •••• ••••'
                },
                expirationDate: {
                    selector: '#id_expiration_date',
                    placeholder: 'MM/YYYY'
                },
                cvv: {
                    selector: '#id_cvv',
                    placeholder: '•••'
                },
                postalCode: {
                    selector: '#id_billing_zip',
                    placeholder: 'Billing Zip Code'
                }

            }
        };
        braintree.hostedFields.create(options, function (err, fields) {
            if (err) {
                console.error(err);
                return;
            }
            hostedFields = fields;
        });
    });
});
