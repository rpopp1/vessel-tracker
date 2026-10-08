export function vesselOpacityExpression(fadeHours: number) {
  return [
    "case",
    [">", ["to-number", ["get", "age_h"], 0], fadeHours], 0.35,
    ["==", ["get", "laden"], null], 0.6,
    1,
  ];
}

type StyleLike = { layers?: { id?: string; layout?: Record<string, unknown> }[] };

/** First usable text-font array found in a loaded style, else undefined. */
export function pickTextFont(style: StyleLike): string[] | undefined {
  for (const layer of style.layers ?? []) {
    const f = layer.layout?.["text-font"];
    if (Array.isArray(f) && f.length > 0 && f.every((x) => typeof x === "string")) return f as string[];
  }
  return undefined;
}
