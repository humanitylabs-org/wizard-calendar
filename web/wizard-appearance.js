/* Calendar domain palette, ported from the live Calendar. Appearance transport,
 * tokens, skin selection and live changes remain owned by shared WizardApp. */
window.CalendarAppearance = Object.freeze({
  colourCalendars(doc) {
    const slots = new Map(); let n = 0;
    for (const cal of doc?.calendars || []) {
      slots.set(cal.id, /#holiday@/.test(cal.id) ? 'var(--k-holiday)' : `var(--k${n++ % 5})`);
      cal.color = slots.get(cal.id);
    }
    for (const event of doc?.events || []) if (slots.has(event.cal)) event.color = slots.get(event.cal);
  }
});
