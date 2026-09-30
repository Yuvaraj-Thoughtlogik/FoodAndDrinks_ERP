# -*- coding: utf-8 -*-
"""Shared "fit every label on ONE page" helpers for the ReportLab label reports.

How a label is fitted:
1. The report builds its story at scale 1.0 (the approved design). If it fits
   the printable area, it is printed unchanged.
2. If it is too tall, a binary search finds the LARGEST font scale (fonts,
   leading, spacing and stamps are all multiplied by it) at which the whole
   label fits. Text is re-wrapped at the smaller size, so it uses the full
   label width.
3. As a final guarantee the story is wrapped in a KeepInFrame(mode='shrink')
   the size of the printable area. If the content is still too big at the
   minimum font scale, it is scaled down as a block. A label therefore
   never flows onto a second page.
"""
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import BaseDocTemplate, Frame, KeepInFrame, PageTemplate, SimpleDocTemplate

# Lowest font scale the reflow search tries. Below this, KeepInFrame shrinks
# the block instead.
DEFAULT_MIN_SCALE = 0.4
# Small safety margin (points) so rounding never pushes a label over the frame.
FIT_EPSILON = 0.5
# Binary search iterations - 10 gives a precision of about 0.06% of the scale.
SEARCH_STEPS = 10


def _do_nothing(canvas_obj, doc):
    pass


class LabelDocTemplate(SimpleDocTemplate):
    """SimpleDocTemplate with a ZERO-padding frame.

    SimpleDocTemplate's default frame adds 6pt padding on every side, so the
    real drawing area is 12pt smaller than PRINTABLE_WIDTH x PRINTABLE_HEIGHT.
    With zero padding, the size we measure is exactly the size we draw.
    """

    def build(self, flowables, onFirstPage=_do_nothing, onLaterPages=_do_nothing,
              canvasmaker=rl_canvas.Canvas):
        self._calc()
        frame = Frame(
            self.leftMargin, self.bottomMargin, self.width, self.height,
            id='normal', leftPadding=0, bottomPadding=0, rightPadding=0, topPadding=0,
        )
        self.addPageTemplates([
            PageTemplate(id='First', frames=frame, onPage=onFirstPage, pagesize=self.pagesize),
            PageTemplate(id='Later', frames=frame, onPage=onLaterPages, pagesize=self.pagesize),
        ])
        BaseDocTemplate.build(self, flowables, canvasmaker=canvasmaker)


def measure_story_height(story, avail_width):
    """Total height the flowables need when wrapped at avail_width."""
    total = 0.0
    for flowable in story:
        try:
            _w, height = flowable.wrap(avail_width, 0x7FFFFFFF)
        except Exception:  # noqa: BLE001 - a bad flowable must not break the print
            height = 0
        total += height
        try:
            total += flowable.getSpaceBefore() + flowable.getSpaceAfter()
        except Exception:  # noqa: BLE001
            pass
    return total


def find_fit_scale(build_story, avail_width, avail_height, min_scale=DEFAULT_MIN_SCALE):
    """Largest scale in [min_scale, 1.0] at which build_story(scale) fits.

    build_story: callable(scale) -> list of NEW flowables (called several times).
    Returns min_scale if even that does not fit. KeepInFrame then handles it.
    """
    target = avail_height - FIT_EPSILON

    def fits(scale):
        return measure_story_height(build_story(scale), avail_width) <= target

    if fits(1.0):
        return 1.0
    if not fits(min_scale):
        return min_scale
    low, high = min_scale, 1.0  # low always fits, high never fits
    for _i in range(SEARCH_STEPS):
        mid = (low + high) / 2.0
        if fits(mid):
            low = mid
        else:
            high = mid
    return low


def keep_in_one_page(story, avail_width, avail_height):
    """Wrap one label's story so it can never overflow onto a new page."""
    return [KeepInFrame(
        avail_width, avail_height - FIT_EPSILON, story,
        mode='shrink', hAlign='CENTER', vAlign='TOP',
    )]


def label_cache_key(label):
    """Hashable key for a label dict. Copies of the same product give the same
    key, so the fit search runs only once per product."""
    try:
        return repr(sorted(label.items()))
    except Exception:  # noqa: BLE001
        return None


def build_fitted_label(build_story, avail_width, avail_height, min_scale=DEFAULT_MIN_SCALE,
                       cache=None, cache_key=None):
    """Return the flowables for ONE label, always fitting on one page.

    build_story: callable(scale) -> list of new flowables for this label.
    cache/cache_key: optional dict + key to reuse the scale found for an
    identical label (for example, when several copies are printed).
    """
    scale = None
    if cache is not None and cache_key is not None:
        scale = cache.get(cache_key)
    if scale is None:
        scale = find_fit_scale(build_story, avail_width, avail_height, min_scale)
        if cache is not None and cache_key is not None:
            cache[cache_key] = scale
    return keep_in_one_page(build_story(scale), avail_width, avail_height)