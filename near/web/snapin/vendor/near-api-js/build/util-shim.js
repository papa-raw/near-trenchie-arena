// Minimal `util` for generate-function (transitive of is-my-json-valid): only util.format is called.
function format(f) {
  var a = Array.prototype.slice.call(arguments, 1), i = 0;
  if (typeof f !== 'string') return [f].concat(a).map(String).join(' ');
  var s = f.replace(/%[sdj%]/g, function (m) {
    if (m === '%%') return '%';
    if (i >= a.length) return m;
    var v = a[i++];
    return m === '%d' ? String(Number(v)) : m === '%j' ? JSON.stringify(v) : String(v);
  });
  for (; i < a.length; i++) s += ' ' + String(a[i]);
  return s;
}
module.exports = { format: format };
