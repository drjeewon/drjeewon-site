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

// 지금 진료 중인지 (한국 시간 기준)
(function () {
  var el = document.querySelector('.live');
  if (!el) return;
  try {
    var hours = JSON.parse(el.dataset.hours || '[]');
    var lunch = JSON.parse(el.dataset.lunch || '[]');
    var names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    var short = ['일', '월', '화', '수', '목', '금', '토'];
    var now = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
    var day = now.getDay(), min = now.getHours() * 60 + now.getMinutes();
    var toMin = function (t) { var p = t.split(':'); return +p[0] * 60 + +p[1]; };
    var today = hours.filter(function (h) { return h[0].indexOf(names[day]) >= 0; })[0];
    var text, cls;
    if (!today) { text = short[day] + ' · 오늘 휴진'; cls = 'off'; }
    else if (min < toMin(today[1])) { text = short[day] + ' · 진료 전 · ' + today[1] + ' 진료 시작'; cls = 'before'; }
    else if (min >= toMin(today[2])) { text = short[day] + ' · 진료 마감'; cls = 'off'; }
    else if (lunch.length && day !== 6 && min >= toMin(lunch[0]) && min < toMin(lunch[1])) { text = '점심시간 · ' + lunch[1] + ' 진료 재개'; cls = 'break'; }
    else { text = '진료 중 · ' + today[2] + ' 마감'; cls = 'open'; }
    el.textContent = text;
    el.classList.add('on', cls);
  } catch (e) {}
})();

// 아래 예약 바 문구 돌리기
(function () {
  var dock = document.querySelector('.dock');
  if (!dock) return;
  var msgs = JSON.parse(dock.dataset.msgs || '[]');
  var a = dock.querySelector('.dock-msg'), span = a.querySelector('span'), i = 0;
  if (msgs.length < 2) return;
  setInterval(function () {
    i = (i + 1) % msgs.length;
    a.classList.add('fade');
    setTimeout(function () { span.textContent = msgs[i][0]; a.href = msgs[i][1]; a.classList.remove('fade'); }, 250);
  }, 4000);
})();

// 칼럼 제목 검색
(function () {
  var input = document.querySelector('.col-search input');
  if (!input) return;
  input.addEventListener('input', function () {
    var q = input.value.trim();
    document.querySelectorAll('.col-card').forEach(function (c) {
      c.style.display = !q || c.textContent.indexOf(q) >= 0 ? '' : 'none';
    });
  });
})();
