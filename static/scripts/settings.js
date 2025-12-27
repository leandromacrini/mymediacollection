document.querySelectorAll('form').forEach(function(form) {
    form.addEventListener('submit', function(event) {
      var submitter = event.submitter;
      if (!submitter || submitter.value !== 'test') {
        return;
      }
      event.preventDefault();
      submitter.disabled = true;
      var originalText = submitter.textContent;
      submitter.textContent = 'Test...';
      var formData = new FormData(form);
      formData.set('action', 'test');
      fetch(form.getAttribute('action') || window.location.pathname, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: formData
      }).then(function(resp) {
        return resp.json();
      }).then(function(data) {
        if (window.showToast) {
          showToast(data.message || 'Test completato.', data.category || (data.ok ? 'success' : 'danger'));
        }
      }).catch(function() {
        if (window.showToast) {
          showToast('Errore durante il test.', 'danger');
        }
      }).finally(function() {
        submitter.disabled = false;
        submitter.textContent = originalText;
      });
    });
  });
