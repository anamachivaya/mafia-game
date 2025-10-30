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
  // Create a fixed, GPU-accelerated background layer instead of using
  // `body` backgroundPosition. This yields much smoother motion on mobile.
  // Clear any body-level background so it doesn't conflict.
  try{ document.body.style.backgroundImage = 'none'; }catch(e){}

  const bg = document.createElement('div');
  bg.className = 'halloween-bg';
  bg.style.backgroundImage = "url('" + pick + "')";
  // Ensure the background tiles top-to-bottom and always fills the width.
  bg.style.backgroundRepeat = 'repeat-y';
  bg.style.backgroundSize = '100% auto';
  bg.style.backgroundPosition = 'center top';
  // Insert as the first child so it's behind other content (z-index:-1)
  if(document.body.firstChild){
    document.body.insertBefore(bg, document.body.firstChild);
  }else{
    document.body.appendChild(bg);
  }

        let latestScroll = 0;
        let ticking = false;
        // Tune the easing to reduce bounciness: increase the lerp alpha so the
        // background follows more responsively (less perceived overshoot), and
        // slightly lower the factor so motion isn't overly strong.
        const factor = 0.45; // background moves at 45% of scroll (slightly reduced)

        // For a non-bouncy (immediate) parallax, map scroll directly to the
        // background offset on each animation frame. This removes any easing
        // and therefore removes the "bouncy" lag when you stop scrolling.
        function updateBackground(){
          const sc = latestScroll;
          const display = Number((sc * factor).toFixed(2));
          // Translate the fixed background layer using transform which is
          // GPU-accelerated and smoother on mobile than changing
          // background-position.
          // NOTE: use negative display to restore the previous direction
          // (background moves opposite in visual space so the foreground
          // appears to move faster). This reverts the inverted behavior.
          bg.style.transform = `translate3d(0, ${-display}px, 0)`;
          ticking = false;
        }

        window.addEventListener('scroll', function(){
          latestScroll = window.scrollY || window.pageYOffset || 0;
          if(!ticking){
            window.requestAnimationFrame(updateBackground);
            ticking = true;
          }
        }, { passive: true });

  // initial set: align currentOffset to the initial scroll position
  latestScroll = window.scrollY || window.pageYOffset || 0;
  // run a single update to apply initial position
  updateBackground();

      }catch(e){console.warn('halloween bg failed', e)}
    });
  }catch(e){console.warn('halloween init failed', e)}
})();
