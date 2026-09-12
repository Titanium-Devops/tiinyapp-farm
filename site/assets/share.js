for (const button of document.querySelectorAll('[data-share]')) {
  const status = button.parentElement.querySelector('[data-share-status]');
  let timer;
  button.addEventListener('click', async () => {
    const url = document.querySelector('link[rel="canonical"]')?.href || location.href;
    const data = { title: button.dataset.shareTitle || document.title, text: button.dataset.shareText || '', url };
    clearTimeout(timer);
    if (status) status.textContent = '';
    try {
      if (navigator.share) {
        await navigator.share(data);
        return;
      }
      await navigator.clipboard.writeText(url);
      if (status) status.textContent = 'Link copied';
      timer = setTimeout(() => { if (status) status.textContent = ''; }, 2000);
    } catch (error) {
      if (error.name !== 'AbortError' && status) status.textContent = 'Could not share. Copy the URL from your address bar.';
    }
  });
}
