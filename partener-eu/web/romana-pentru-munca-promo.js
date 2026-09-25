(()=>{'use strict';
function mount(){
  if(document.querySelector('[data-rpm-promo]'))return;
  const main=document.querySelector('.main'); if(!main)return;
  const anchor=document.querySelector('.conciergeTrust')||document.querySelector('.conciergeSurface')||document.querySelector('.hero');
  if(!anchor)return;
  const box=document.createElement('section');
  box.className='rpmPromo'; box.dataset.rpmPromo='1';
  box.setAttribute('aria-label','Română pentru Muncă');
  box.innerHTML='<a class="rpmPromoVisual" href="/romana-pentru-munca/" aria-label="Vezi Română pentru Muncă"><img class="rpmPromoImg" src="https://images.pexels.com/photos/7698712/pexels-photo-7698712.jpeg?w=1080" alt="Adulți într-o sesiune de formare și colaborare la locul de muncă" loading="lazy" decoding="async"></a><div class="rpmPromoCopy"><small>Serviciu pentru angajatori</small><strong>Ai angajați străini? Vezi „Română pentru Muncă”.</strong><p>Organizăm cursul de limba română, programul, participarea și documentele programului.</p><a class="rpmPromoCta" href="/romana-pentru-munca/">Vezi oferta →</a></div>';
  anchor.insertAdjacentElement(anchor.classList.contains('conciergeTrust')?'beforebegin':'afterend',box);
}
window.addEventListener('load',()=>setTimeout(mount,1000),{once:true});
setTimeout(mount,1400);
})();