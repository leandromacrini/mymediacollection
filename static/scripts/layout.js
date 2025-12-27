function showToast(message, category) {
  var container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container position-fixed top-0 end-0 p-3';
    container.style.zIndex = '1080';
    document.body.appendChild(container);
  }
  var toastClass = 'text-bg-info';
  if (category === 'success') toastClass = 'text-bg-success';
  if (category === 'danger' || category === 'error') toastClass = 'text-bg-danger';
  if (category === 'warning') toastClass = 'text-bg-warning';
  var toastEl = document.createElement('div');
  toastEl.className = 'toast ' + toastClass + ' border-0 mb-2';
  toastEl.setAttribute('role', 'alert');
  toastEl.setAttribute('aria-live', 'assertive');
  toastEl.setAttribute('aria-atomic', 'true');
  toastEl.setAttribute('data-bs-delay', '3500');
  toastEl.innerHTML = '<div class="d-flex">' +
    '<div class="toast-body">' + message + '</div>' +
    '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
    '</div>';
  container.appendChild(toastEl);
  var toast = new bootstrap.Toast(toastEl, { autohide: true });
  toast.show();
  toastEl.addEventListener('hidden.bs.toast', function() {
    toastEl.remove();
    if (!container.querySelector('.toast')) {
      container.remove();
    }
  });
}

document.querySelectorAll('.toast').forEach(function(el) {
  var toast = new bootstrap.Toast(el, { autohide: true });
  toast.show();
});
