# Figma to CSS Property Mapping

## Colors
- Figma uses 0-1 RGBA: `{r: 0.18, g: 0.55, b: 1.0, a: 1.0}`
- Convert: `round(value * 255)` for each channel
- Output: `#RRGGBB` when alpha is 1, `rgba(R, G, B, A)` otherwise
- Fill opacity multiplies with color alpha

## Typography Edge Cases

### letterSpacing
Can be a plain number (px) or an object:
- `{value: 0.5, unit: "PIXELS"}` → `letter-spacing: 0.5px`
- `{value: 2, unit: "PERCENT"}` → `letter-spacing: {fontSize * 2 / 100}px`

### lineHeight
- `{value: 20, unit: "PIXELS"}` → `line-height: 20px`
- `{value: 150, unit: "PERCENT"}` → `line-height: 150%`
- `{unit: "AUTO"}` → omit (use font default)

### textAutoResize
- `NONE` — fixed size text box
- `HEIGHT` — auto height, fixed width
- `WIDTH_AND_HEIGHT` — auto size
- `TRUNCATE` — fixed size with text truncation

## Layout

### Stroke Alignment
Figma supports three modes; CSS `border` is always outside:
- `INSIDE` — Figma draws stroke inside the element (use `box-shadow: inset 0 0 0 Npx color` as workaround)
- `OUTSIDE` — matches CSS `border`
- `CENTER` — half inside, half outside (no direct CSS equivalent)

### Sizing Modes
- `layoutSizingHorizontal: "FIXED"` → use `absoluteBoundingBox.width`
- `layoutSizingHorizontal: "FILL"` → `flex: 1` (or `width: 100%`)
- `layoutSizingHorizontal: "HUG"` → omit width (auto)
- Same pattern for vertical

## Effects

### Gradient Angle Calculation
Figma provides `gradientHandlePositions` as [start, end, width]:
```
angle_rad = atan2(end.y - start.y, end.x - start.x)
css_angle = (degrees(angle_rad) + 90) % 360
```

### Image Fills
Nodes with `fills: [{type: "IMAGE"}]` contain an `imageRef` hash but not a downloadable URL. Use `export_image.py` to get the actual rendered image.
