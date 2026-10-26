/* Zoom-on-click lightbox for the rendered demos in site/index.html.

   The embeds used to size themselves by aspect ratio alone: the width
   filled the figure and the height followed it, so the tall portrait
   captures (the editor index, a quarter of a browser window per pixel)
   towered over their section while the wide studio captures collapsed
   into letterbox strips -- and every one of them was far too big to be
   nothing but a preview.  Now this script lays each embed out as a small
   thumbnail of one uniform height: the width follows the capture's true
   aspect ratio, except for the mock e-readers, whose inline ratios are
   written inverted (760/420 recorded for a 420x760 portrait device) and
   so are corrected here.

   Clicking a thumbnail opens that same iframe almost full screen: a dark
   backdrop covers the page, the frame sits centred above it, and either
   clicking anywhere outside the frame or pressing escape closes it again.

   The opening click lands on a transparent button overlaid on the figure,
   never inside the embed's own document: events inside a srcdoc iframe do
   not reach the parent page at all -- no listener here could catch them
   even in principle -- and beyond that, the story demos carry live choice
   links, so opening must swallow exactly one click before interaction
   begins.  While an embed is zoomed its overlay button is hidden, which
   keeps the demo fully interactive; the overlay returns when it closes.

   Without javascript nothing here runs: no buttons appear and no sizing
   is applied, so the embeds stay as their markup authored them. */

(function () {
  "use strict";

  /* True width/height ratios for captures whose authored ratio differs
     from what this layout should honour; keyed by the tail of each
     iframe's title attribute ("reader-beware device red shirt"). */
  var RATIOS = {
    "device red shirt": 420 / 760,
    "device green shirt": 420 / 760,
  };

  /* Uniform thumbnail height on roomy screens; narrower columns fall
     back to width/ratio, so thumbnails shrink with their figure instead
     of ever escaping it. */
  var THUMB_HEIGHT = 300;
  /* Even a squeezed capture stays a clickable preview, not a sliver. */
  var MIN_THUMB_HEIGHT = 60;

  var frames = [];
  var current = null;
  var backdrop = null;

  function titleTail(frame) {
    return frame.title.replace(/^reader-beware\s/, "");
  }

  function figureOf(frame) {
    return frame.closest("figure") || frame.parentElement;
  }

  function ratioOf(frame) {
    var tail = titleTail(frame);
    if (RATIOS.hasOwnProperty(tail)) {
      return RATIOS[tail];
    }
    /* the render script writes each embed's authored ratio inline */
    var authored = parseFloat(frame.style.aspectRatio);
    return isFinite(authored) && authored > 0 ? authored : 1.5;
  }

  function layout(frame) {
    if (frame.classList.contains("zoomed")) {
      return;
    }
    var figure = figureOf(frame);
    /* Measure the column, not the capture: an iframe at its authored
       width would inflate a flex figure's clientWidth, so the frame is
       collapsed to nothing first and re-sized in the same synchronous
       pass -- no intermediate paint between them. */
    frame.style.width = "0";
    var available = figure.clientWidth;
    var height = Math.min(
      THUMB_HEIGHT,
      Math.max(MIN_THUMB_HEIGHT, Math.floor(available / ratioOf(frame)))
    );
    frame.style.width = Math.round(height * ratioOf(frame)) + "px";
    frame.style.height = height + "px";
    /* the opening button covers exactly the thumbnail it opens: the
       caption under it stays selectable text, not a hit target */
    if (frame.zoomButton) {
      /* rectangles, not offsetParent arithmetic: figures are positioned
         in style.css, but reading both boxes once the frame has been
         sized lands the overlay wherever the thumbnail really sits */
      var button = frame.zoomButton;
      var screen = frame.getBoundingClientRect();
      var parent = figure.getBoundingClientRect();
      button.style.top = screen.top - parent.top + "px";
      button.style.left = screen.left - parent.left + "px";
      button.style.width = screen.width + "px";
      button.style.height = screen.height + "px";
    }
  }

  function relayout() {
    frames.forEach(layout);
  }

  function ensureBackdrop() {
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "zoom-backdrop";
      backdrop.addEventListener("click", close);
      document.body.appendChild(backdrop);
    }
    backdrop.style.display = "block";
    return backdrop;
  }

  function open(frame) {
    if (current && current !== frame) {
      close();
    }
    ensureBackdrop();
    document.body.classList.add("zoom-open");
    frame.classList.add("zoomed");
    /* the demo itself must take clicks once zoomed */
    frame.zoomButton.style.display = "none";
    current = frame;
  }

  function close() {
    if (!current) {
      return;
    }
    var frame = current;
    frame.classList.remove("zoomed");
    document.body.classList.remove("zoom-open");
    backdrop.style.display = "none";
    frame.zoomButton.style.display = "";
    current = null;
    layout(frame);
    /* keyboard users end where they began: on the thumbnail button */
    frame.zoomButton.focus();
  }

  function decorate(frame) {
    if (titleTail(frame).indexOf("device ") === 0) {
      /* styled as its own kind of zoom: a phone-sized box, not a wide one */
      frame.setAttribute("data-device", "");
    }
    var button = document.createElement("button");
    button.type = "button";
    button.className = "zoom-button";
    button.title = "Click to enlarge";
    button.setAttribute("aria-label", "Enlarge demo: " + titleTail(frame));
    button.addEventListener("click", function () {
      open(frame);
    });
    figureOf(frame).appendChild(button);
    frame.zoomButton = button;
  }

  function init() {
    frames = Array.prototype.slice.call(
      document.querySelectorAll("iframe.embed")
    );
    frames.forEach(function (frame) {
      decorate(frame);
      layout(frame);
    });
    window.addEventListener("resize", relayout);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        close();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
