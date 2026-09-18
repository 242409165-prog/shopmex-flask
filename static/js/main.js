// Auto-dismiss alerts after 5 seconds
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(a => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(a);
      if (bsAlert) bsAlert.close();
    });
  }, 5000);
});
