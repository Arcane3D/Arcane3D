---
name: image-to-dxf-laser-cut
description: Convert attached PNG images and SVG artwork into dimensioned DXF vector outlines for laser cutting, CNC, and CAD workflows.
---

# Image to DXF for laser cutting

Use the `image_to_dxf` MCP tool when the user supplies PNG, SVG, or other supported raster artwork and asks for a DXF suitable for laser cutting, CNC, or CAD.

## Workflow

1. Use the image attached by the user as the input file. Pass the file's supported download URL and metadata to the MCP tool.
2. Use the requested finished width in millimetres. When the user has not specified a width, ask for it before converting.
3. For dark artwork on a light background, use `invert: false`. For light artwork on a dark background, use `invert: true`.
4. Use automatic thresholding by default (`threshold: 0`). If tracing misses details, adjust threshold between 1 and 254.
5. Use a low `tolerance_mm` for detailed artwork (for example, 0.1 mm). Larger values simplify outlines more aggressively.
6. After a successful tool result, report the resulting width, height, path count, and DXF download link.

## Capabilities

- PNG and other supported raster artwork to DXF outlines.
- SVG paths to DXF.
- Width-based scaling in millimetres.
- Raster outer and inner contours on `OUTER` and `INNER` layers.
- SVG paths on the `PATHS` layer.
- Threshold, inversion, and outline simplification controls.

## Limitations and safety checks

- This is outline tracing, not centerline tracing or photo engraving.
- Photographs become black-and-white contours and usually need manual preparation.
- SVG text should be converted to paths before conversion.
- The server limits remote input files to 15 MB and raster images to 40 megapixels.
- Converted DXF links expire after one hour.
- Before cutting, inspect the DXF in the target CAD/laser application and verify dimensions, contour closure, kerf compensation, material, and machine-specific settings. Do not claim that an output has been physically validated for a laser machine.
