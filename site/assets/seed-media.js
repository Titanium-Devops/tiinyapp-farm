const dialog = document.getElementById('gallery-dialog');
if (dialog) {
  const image = document.getElementById('gallery-image');
  document.querySelectorAll('[data-gallery-image]').forEach(anchor => {
    anchor.addEventListener('click', event => {
      event.preventDefault();
      image.src = anchor.href;
      image.alt = anchor.querySelector('img').alt;
      dialog.showModal();
    });
  });
  dialog.addEventListener('click', event => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    }
  });
}
document.querySelectorAll('[data-youtube-id]').forEach(button => {
  button.addEventListener('click', () => {
    const id = button.dataset.youtubeId;
    if (!/^[A-Za-z0-9_-]{11}$/.test(id)) return;
    const frame = document.createElement('iframe');
    frame.src = 'https://www.youtube-nocookie.com/embed/' + id + '?autoplay=1';
    frame.title = button.getAttribute('aria-label');
    frame.allow = 'autoplay; encrypted-media; picture-in-picture';
    frame.allowFullscreen = true;
    frame.referrerPolicy = 'strict-origin-when-cross-origin';
    frame.className = 'seed-video';
    button.replaceWith(frame);
    frame.focus();
  });
});
