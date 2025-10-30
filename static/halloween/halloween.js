(function(){
  try{
    const imgs = [
      '/static/halloween/img2.jpg',
      '/static/halloween/img3.jpg',
      '/static/halloween/img4.png',
      '/static/halloween/img5.png'
    ];
    // pick random image
    const pick = imgs[Math.floor(Math.random()*imgs.length)];
    // apply the chosen image to the body (no global dark overlay)
    document.addEventListener('DOMContentLoaded', function(){
      try{
        document.body.style.backgroundImage = "url('" + pick + "')";
        document.body.style.backgroundSize = 'cover';
        // start with centered position; we'll adjust on scroll for a parallax effect
        document.body.style.backgroundPosition = 'center center';
        // use 'scroll' attachment so mobile browsers behave consistently
        document.body.style.backgroundAttachment = 'scroll';
        document.body.style.backgroundRepeat = 'no-repeat';

        // Simpler subtle parallax: move the background a fixed fraction of the
        // page scroll. This is lighter-weight and meets the user's request for
        // a weaker parallax (factor 0.25). Background remains 'cover' to avoid
        // empty horizontal gaps.

        document.body.style.backgroundSize = 'cover';
        document.body.style.backgroundPosition = 'center center';

        let latestScroll = 0;
        let ticking = false;
        const factor = 0.25; // user-requested weaker parallax (25% of scroll)

        function updateBackground(){
          const sc = latestScroll;
          const y = Math.round(sc * factor);
          // Use center-based offset so cover images pan naturally
          document.body.style.backgroundPosition = `center calc(50% + ${-y}px)`;
          ticking = false;
        }

        window.addEventListener('scroll', function(){
          latestScroll = window.scrollY || window.pageYOffset || 0;
          if(!ticking){
            window.requestAnimationFrame(updateBackground);
            ticking = true;
          }
        }, { passive: true });

        // initial set
        latestScroll = window.scrollY || window.pageYOffset || 0;
        updateBackground();

      }catch(e){console.warn('halloween bg failed', e)}
    });
  }catch(e){console.warn('halloween init failed', e)}
})();
