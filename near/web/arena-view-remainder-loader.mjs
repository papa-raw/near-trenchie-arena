// Resolve the browser import map for the focused Node geometry case.
export function resolve(specifier, context, nextResolve) {
  if (specifier === 'three') return nextResolve(new URL('./vendor/three/three.module.min.js', import.meta.url).href, context);
  return nextResolve(specifier, context);
}
