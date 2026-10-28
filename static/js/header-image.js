/** Upload and restore the station's persistent header icon. */
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('cfg-header-image');
    const reset = document.getElementById('cfg-header-image-reset');
    const status = document.getElementById('cfg-header-image-status');
    if (!input || !reset || !status) return;

    async function save(file) {
        input.disabled = reset.disabled = true;
        status.textContent = file ? 'Saving header icon...' : 'Restoring default icon...';
        try {
            if (file && file.size > 10 * 1024 * 1024) throw new Error('Choose an image of 10 MB or smaller.');
            const options = { method: file ? 'POST' : 'DELETE' };
            if (file) {
                const data = await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result);
                    reader.onerror = () => reject(new Error('Unable to read this image.'));
                    reader.readAsDataURL(file);
                });
                options.headers = { 'Content-Type': 'application/json' };
                options.body = JSON.stringify({ data });
            }
            const response = await fetch('/api/header-image', options);
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || 'Unable to save header icon.');
            const imageURL = `/api/header-image?v=${Date.now()}`;
            document.getElementById('header-custom-image').src = imageURL;
            document.getElementById('header-image-preview').src = imageURL;
            status.textContent = file ? 'Header icon saved.' : 'Default icon restored.';
        } catch (error) {
            status.textContent = error.message;
        } finally {
            input.disabled = reset.disabled = false;
            input.value = '';
        }
    }
    input.addEventListener('change', () => { if (input.files?.[0]) save(input.files[0]); });
    reset.addEventListener('click', () => save(null));
});
