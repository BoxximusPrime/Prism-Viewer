(() => {
  const items = [...document.querySelectorAll('[data-lightbox]')];
  const modal = document.querySelector('[data-lightbox-modal]');
  const modalImage = document.querySelector('[data-lightbox-image]');
  const modalCaption = document.querySelector('[data-lightbox-caption]');
  const previousButton = document.querySelector('[data-lightbox-prev]');
  const nextButton = document.querySelector('[data-lightbox-next]');
  let lastFocused;
  let currentIndex = 0;
  let wheelLocked = false;

  const closeLightbox = () => {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    modalImage.src = '';
    document.body.style.overflow = '';
    lastFocused?.focus();
  };

  const showItem = (index) => {
    currentIndex = (index + items.length) % items.length;
    const item = items[currentIndex];
    modalImage.src = item.dataset.lightbox;
    modalImage.alt = item.querySelector('img').alt;
    modalCaption.textContent = item.dataset.caption;
  };

  const openLightbox = (item) => {
    lastFocused = item;
    showItem(items.indexOf(item));
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    modal.querySelector('.lightbox-close').focus();
  };

  const navigateLightbox = (direction) => showItem(currentIndex + direction);

  items.forEach((item) => item.addEventListener('click', () => openLightbox(item)));
  previousButton.addEventListener('click', () => navigateLightbox(-1));
  nextButton.addEventListener('click', () => navigateLightbox(1));

  modal.addEventListener('wheel', (event) => {
    if (!modal.classList.contains('is-open')) return;
    event.preventDefault();
    if (wheelLocked || event.deltaY === 0) return;
    wheelLocked = true;
    navigateLightbox(event.deltaY > 0 ? 1 : -1);
    window.setTimeout(() => { wheelLocked = false; }, 350);
  }, { passive: false });

  modal.querySelectorAll('[data-lightbox-close]').forEach((button) => button.addEventListener('click', closeLightbox));
  document.addEventListener('keydown', (event) => {
    if (!modal.classList.contains('is-open')) return;
    if (event.key === 'Escape') closeLightbox();
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      navigateLightbox(-1);
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      navigateLightbox(1);
    }
  });
})();
