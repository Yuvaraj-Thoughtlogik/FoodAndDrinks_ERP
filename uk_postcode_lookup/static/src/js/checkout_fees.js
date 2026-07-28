/** Show Stripe fee notice when Stripe is selected at checkout */
document.addEventListener('DOMContentLoaded', function () {
    const paymentForms = document.querySelectorAll('.o_payment_option_card');
    paymentForms.forEach(function (card) {
        const label = card.querySelector('label');
        if (label && label.textContent.toLowerCase().includes('stripe')) {
            const feeNotice = card.querySelector('.tr_stripe_fee_notice');
            if (!feeNotice) {
                const notice = document.createElement('div');
                notice.className = 'tr_stripe_fee_notice text-muted';
                notice.style.fontSize = '12px';
                notice.style.marginTop = '4px';
                notice.textContent = 'A Stripe processing fee will be added to your total.';
                card.appendChild(notice);
            }
        }
    });
});
