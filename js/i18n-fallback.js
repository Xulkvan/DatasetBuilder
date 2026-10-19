// V11.10.1: Fallback для i18n, если основной файл не загрузился
if (typeof window.t !== "function") {
  window.t = function(k, params) {
    if (params) for (var p in params) {
      k = String(k).replace(new RegExp("\\{" + p + "\\}", "g"), params[p]);
    }
    return k;
  };
}
