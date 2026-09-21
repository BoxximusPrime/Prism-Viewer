(() => {
  const gallery = document.querySelector('[data-gallery]');
  const items = [...document.querySelectorAll('[data-lightbox]')];
  const modal = document.querySelector('[data-lightbox-modal]');
  const modalImage = document.querySelector('[data-lightbox-image]');
  const modalCaption = document.querySelector('[data-lightbox-caption]');
  let lastFocused;

  const moveGallery = (direction) => {
    gallery.scrollBy({ left: direction * Math.min(gallery.clientWidth * .72, 620), behavior: 'smooth' });
  };

  document.querySelector('[data-gallery-prev]').addEventListener('click', () => moveGallery(-1));
  document.querySelector('[data-gallery-next]').addEventListener('click', () => moveGallery(1));

  gallery.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft') moveGallery(-1);
    if (event.key === 'ArrowRight') moveGallery(1);
  });

  const closeLightbox = () => {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    modalImage.src = '';
    document.body.style.overflow = '';
    lastFocused?.focus();
  };

  items.forEach((item) => item.addEventListener('click', () => {
    lastFocused = item;
    modalImage.src = item.dataset.lightbox;
    modalImage.alt = item.querySelector('img').alt;
    modalCaption.textContent = item.dataset.caption;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    modal.querySelector('.lightbox-close').focus();
  }));

  modal.querySelectorAll('[data-lightbox-close]').forEach((button) => button.addEventListener('click', closeLightbox));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-open')) closeLightbox();
  });
})();
