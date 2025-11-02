// static/script.js - MINIMAL VERSION
document.addEventListener('DOMContentLoaded', function() {
    // Grade field toggle for registration
    const roleSelect = document.getElementById('role');
    const gradeField = document.getElementById('gradeField');
    
    if (roleSelect && gradeField) {
        roleSelect.addEventListener('change', function() {
            const isStudent = this.value === 'student';
            gradeField.style.display = isStudent ? 'block' : 'none';
            
            const gradeSelect = document.getElementById('grade');
            if (gradeSelect) {
                gradeSelect.required = isStudent;
                if (!isStudent) gradeSelect.value = '';
            }
        });
    }

    // Auto-dismiss alerts after 5 seconds
    setTimeout(function() {
        const alerts = document.querySelectorAll('.alert');
        alerts.forEach(function(alert) {
            const closeBtn = alert.querySelector('.btn-close');
            if (closeBtn) closeBtn.click();
        });
    }, 5000);
});