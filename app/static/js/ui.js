/*
 * EDUCATIONAL SECURITY TRAINING ENVIRONMENT
 * Shared page behaviour, served from 'self' so the Content-Security-Policy
 * (script-src 'self' + nonce) allows it.
 *
 * Templates used to carry inline handlers (onclick="return confirm(...)",
 * onchange="this.form.submit()"). The CSP blocks every one of them, so none
 * ever ran: confirmations were skipped and some controls were dead. Templates
 * now declare the behaviour with data-* attributes and this file does it,
 * through event delegation, for elements present now and added later.
 *
 *   data-confirm="Question?"      on a <form>, or on a submit <button>/<a>
 *   data-autosubmit               on an input/select: submit its form on change
 *   data-toggle-password="id"     on a button: show/hide the password field
 *   data-submit-form="id"         on a link/button: submit the form with that id
 */
(function () {
  'use strict';

  // A confirmation on the clicked control (button or link).
  document.addEventListener('click', function (event) {
    var el = event.target.closest('[data-confirm]');
    if (el && el.tagName !== 'FORM' && !window.confirm(el.getAttribute('data-confirm'))) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  // A confirmation on the form itself (any way of submitting it).
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (form.matches('form[data-confirm]') && !window.confirm(form.getAttribute('data-confirm'))) {
      event.preventDefault();
    }
  }, true);

  document.addEventListener('change', function (event) {
    var el = event.target.closest('[data-autosubmit]');
    if (el && el.form) {
      el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
    }
  });

  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-toggle-password]');
    if (!btn) { return; }
    var input = document.getElementById(btn.getAttribute('data-toggle-password'));
    if (!input) { return; }
    var show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    var icon = btn.querySelector('i');
    if (icon) {
      icon.classList.toggle('bi-eye', !show);
      icon.classList.toggle('bi-eye-slash', show);
    }
    btn.setAttribute('aria-pressed', show ? 'true' : 'false');
  });

  document.addEventListener('click', function (event) {
    var el = event.target.closest('[data-submit-form]');
    if (!el) { return; }
    var form = document.getElementById(el.getAttribute('data-submit-form'));
    if (form) {
      event.preventDefault();
      form.requestSubmit ? form.requestSubmit() : form.submit();
    }
  });
}());
