document.querySelectorAll('.selfcheck').forEach(function (box) {
  var out = box.querySelector('.result');
  var rules = JSON.parse(box.dataset.rules || '[]');
  function update() {
    var n = box.querySelectorAll('input:checked').length;
    var msg = '항목을 눌러 체크해 보세요.';
    rules.forEach(function (r) { if (n >= r[0]) msg = r[1]; });
    out.textContent = n + '개 선택 · ' + msg;
  }
  box.addEventListener('change', update);
  update();
});
