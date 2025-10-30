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
  // Stretch the image to fit the viewport width, then tile vertically so
  // the page (including the bottom) is always covered. This stitches the
  // image top-to-bottom infinitely and avoids empty bottoms on tall pages.
  document.body.style.backgroundSize = '100% auto';
  document.body.style.backgroundRepeat = 'repeat-y';
  document.body.style.backgroundPosition = 'center top';
  // use 'scroll' attachment so mobile browsers behave consistently
  document.body.style.backgroundAttachment = 'scroll';

        let latestScroll = 0;
        let ticking = false;
  // Make the background move slower than the foreground. Reduce the
  // parallax multiplier so the background pans more subtly.
  // Lower values => background moves slower. Changed from 0.25 -> 0.08.
  const factor = 0.55; // background moves at 8% of scroll

        function updateBackground(){
          const sc = latestScroll;
          const y = Math.round(sc * factor);
          // Move the tiled background in the opposite direction of the page
          // scroll but at a reduced rate so the foreground appears to move
          // faster. Previously the background was moving in the same
          // direction and appeared faster; flipping the sign makes the
          // foreground feel quicker while the background lags behind.
          document.body.style.backgroundPosition = `center ${y}px`;
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
