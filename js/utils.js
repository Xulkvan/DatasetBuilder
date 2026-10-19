// @ts-check
// V11.5.0: Extracted Utilities
export function haptic(type = 'light') {
  if (!('vibrate' in navigator)) return;
  try {
    const ua = navigator.userActivation;
    if (ua && typeof ua.hasBeenActive === 'boolean' && !ua.hasBeenActive) return;
  } catch (e) {}
  const patterns = {
    light: [8], medium: [15], selection: [5],
    success: [10, 40, 12], error: [22, 60, 22, 60, 22], warning: [15, 40, 15],
  };
  try { navigator.vibrate(patterns[type] || patterns.light); } catch (e) {}
}
