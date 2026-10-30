/** The window width the stubbed matchMedia answers for; tests start wide enough for three panes. */
let width = 1400;

export function setViewport(pixels: number) {
  width = pixels;
}

export function resetViewport() {
  width = 1400;
}

export function viewportMatches(query: string): boolean {
  const min = /min-width:\s*(\d+)px/.exec(query);
  const max = /max-width:\s*(\d+)px/.exec(query);
  return (!min || width >= Number(min[1])) && (!max || width <= Number(max[1]));
}
