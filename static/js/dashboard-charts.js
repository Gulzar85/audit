document.addEventListener('DOMContentLoaded', function () {
  var data = window.DASHBOARD_DATA;
  if (!data) return;

  var primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || '#DA291C';
  if (typeof ApexCharts === 'undefined') { console.error('ApexCharts not loaded'); return; }

  if (data.scoreTrends) {
    var scoreTrendOpts = {
      chart: { type: 'area', height: 200, toolbar: { show: false } },
      series: [{ name: 'Score', data: data.scoreTrends.data }],
      xaxis: { categories: data.scoreTrends.labels },
      yaxis: { min: 0, max: 100, labels: { formatter: function (v) { return v + '%'; } } },
      colors: [primaryColor],
      dataLabels: { enabled: false },
      stroke: { curve: 'smooth', width: 2 },
      fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05, stops: [0, 100] } },
      grid: { borderColor: '#e2e8f0' },
      tooltip: { y: { formatter: function (v) { return v + '%'; } } },
    };
    var scoreTrendEl = document.getElementById('scoreTrendChart');
    if (scoreTrendEl) new ApexCharts(scoreTrendEl, scoreTrendOpts).render();
  }

  if (data.gradeDistribution && data.gradeDistribution.length) {
    var donutEl = document.getElementById('gradeDonutChart');
    if (donutEl) {
      var series = data.gradeDistribution.map(function (g) { return g[1].count; });
      var labels = data.gradeDistribution.map(function (g) { return g[0]; });
      var colors = data.gradeDistribution.map(function (g) {
        var grade = g[0];
        return grade === 'A' ? '#10b981' : grade === 'B' ? '#3b82f6' : grade === 'C' ? '#f59e0b' : grade === 'D' ? '#f97316' : '#ef4444';
      });
      if (series.some(function (v) { return v > 0; })) {
        new ApexCharts(donutEl, {
          chart: { type: 'donut', height: 180, toolbar: { show: false } },
          series: series,
          labels: labels,
          colors: colors,
          legend: { show: false },
          dataLabels: { enabled: false },
          stroke: { width: 0 },
          tooltip: { y: { formatter: function (v) { return v + ' audits'; } } },
        }).render();
      }
    }
  }

  if (data.avgScore !== null && data.avgScore !== undefined) {
    var gaugeEl = document.getElementById('overallGauge');
    if (gaugeEl) {
      var score = data.avgScore;
      new ApexCharts(gaugeEl, {
        chart: { type: 'radialBar', height: 200, toolbar: { show: false } },
        series: [score],
        colors: [score >= 90 ? '#10b981' : score >= 80 ? '#f59e0b' : '#ef4444'],
        plotOptions: {
          radialBar: {
            startAngle: -90, endAngle: 90,
            hollow: { size: '60%' },
            track: { background: '#e2e8f0', strokeWidth: '100%' },
            dataLabels: {
              name: { show: false },
              value: { show: true, fontSize: '28px', fontWeight: 800, formatter: function (v) { return Math.round(v) + '%'; }, offsetY: 5 },
            },
          },
        },
        stroke: { lineCap: 'round' },
        tooltip: { enabled: false },
      }).render();
    }
  }

  if (data.sectionPerformance && data.sectionPerformance.length) {
    var perfEl = document.getElementById('sectionPerfChart');
    if (perfEl) {
      var perfData = data.sectionPerformance;
      new ApexCharts(perfEl, {
        chart: { type: 'bar', height: Math.max(220, perfData.length * 42), toolbar: { show: false } },
        series: [{ name: 'Avg %', data: perfData.map(function (s) { return s.avg; }) }],
        plotOptions: { bar: { horizontal: true, borderRadius: 3, barHeight: '55%', distributed: true } },
        xaxis: { categories: perfData.map(function (s) { return s.name; }), max: 100 },
        yaxis: { labels: { style: { fontSize: '9px' } } },
        colors: perfData.map(function (s) { return s.avg >= 90 ? '#10b981' : s.avg >= 80 ? '#f59e0b' : '#ef4444'; }),
        dataLabels: { enabled: true, formatter: function (v) { return v + '%'; }, style: { fontSize: '9px', fontWeight: 700, colors: ['#fff'] }, offsetX: 20 },
        grid: { borderColor: '#e2e8f0' },
        legend: { show: false },
        tooltip: { y: { formatter: function (v) { return v + '%'; } } },
      }).render();
    }
  }

  if (data.sectionDeductions && data.sectionDeductions.length) {
    var dedEl = document.getElementById('sectionDedChart');
    if (dedEl) {
      var dedData = data.sectionDeductions;
      new ApexCharts(dedEl, {
        chart: { type: 'bar', height: Math.max(220, dedData.length * 45), toolbar: { show: false }, stacked: true },
        series: [
          { name: 'Scored', data: dedData.map(function (s) { return s.scored; }) },
          { name: 'Deducted', data: dedData.map(function (s) { return s.deducted; }) },
        ],
        plotOptions: { bar: { horizontal: true, borderRadius: 2, barHeight: '60%' } },
        xaxis: { categories: dedData.map(function (s) { return s.name; }) },
        colors: ['#22c55e', '#ef4444'],
        dataLabels: { enabled: false },
        legend: { position: 'bottom', horizontalAlign: 'center', fontSize: '10px' },
        grid: { borderColor: '#e2e8f0' },
        tooltip: { y: { formatter: function (v) { return v + ' pts'; } } },
      }).render();
    }
  }

  if (data.sectionTrendSeries && data.sectionTrendSeries.length) {
    var trendSeries = data.sectionTrendSeries;
    var trendMonths = data.sectionTrendMonths;
    var trendSelect = document.getElementById('sectionTrendSelect');
    var trendContainer = document.getElementById('sectionTrendChart');
    if (trendSelect && trendContainer) {
      var trendChart = null;
      function buildOpts() {
        trendSelect.innerHTML = '<option value="__all__">All Sections</option>';
        trendSeries.forEach(function (s) {
          var opt = document.createElement('option');
          opt.value = s.name; opt.textContent = s.name; trendSelect.appendChild(opt);
        });
      }
      function renderTrend(selected) {
        var series = selected === '__all__' ? trendSeries : trendSeries.filter(function (s) { return s.name === selected; });
        if (trendChart) { trendChart.destroy(); }
        trendChart = new ApexCharts(trendContainer, {
          chart: { type: 'line', height: 220, toolbar: { show: false } },
          series: series,
          xaxis: { categories: trendMonths },
          yaxis: { min: 0, max: 100, labels: { formatter: function (v) { return v + '%'; } } },
          colors: [primaryColor, '#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'],
          stroke: { curve: 'smooth', width: 2 },
          dataLabels: { enabled: false },
          markers: { size: 3, hover: { size: 5 } },
          grid: { borderColor: '#e2e8f0' },
          tooltip: { y: { formatter: function (v) { return v + '%'; } } },
        });
        trendChart.render();
      }
      buildOpts();
      renderTrend('__all__');
      trendSelect.addEventListener('change', function (e) { renderTrend(e.target.value); });
    }
  }

  if (data.frequentFindings && data.frequentFindings.length) {
    var findings = data.frequentFindings;
    var tbody = document.getElementById('findingsTableBody');
    if (tbody) {
      findings.forEach(function (f, i) {
        var tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-50 transition-colors';
        var td1 = document.createElement('td');
        td1.className = 'py-2.5 pr-2 align-middle';
        var badge = document.createElement('span');
        if (i < 3) {
          badge.className = 'w-5 h-5 rounded inline-flex items-center justify-center text-[9px] font-extrabold shadow-sm ' + (i === 0 ? 'bg-secondary text-accent' : i === 1 ? 'bg-gray-400 text-white' : 'bg-amber-700 text-white');
          badge.textContent = i + 1;
        } else {
          badge.className = 'text-[10px] font-bold text-gray-400 pl-1';
          badge.textContent = i + 1;
        }
        td1.appendChild(badge);
        tr.appendChild(td1);
        var td2 = document.createElement('td');
        td2.className = 'py-2.5 pr-2 font-semibold text-gray-800 max-w-[200px] truncate text-[11px]';
        td2.textContent = f.text;
        tr.appendChild(td2);
        var td3 = document.createElement('td');
        td3.className = 'py-2.5 pr-2 hidden sm:table-cell align-middle';
        var sectionSpan = document.createElement('span');
        sectionSpan.className = 'inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold bg-gray-100 text-gray-600 ';
        sectionSpan.textContent = f.section;
        td3.appendChild(sectionSpan);
        tr.appendChild(td3);
        var td4 = document.createElement('td');
        td4.className = 'py-2.5 text-right align-middle';
        var countSpan = document.createElement('span');
        countSpan.className = 'inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold ' + (f.count >= 5 ? 'bg-red-100 text-red-700 ' : 'bg-orange-100 text-orange-700 ');
        countSpan.textContent = f.count + 'x';
        td4.appendChild(countSpan);
        tr.appendChild(td4);
        tbody.appendChild(tr);
      });
    }
  }

  if (data.caAgingData && data.caAgingData.length) {
    var agingEl = document.getElementById('caAgingChart');
    if (agingEl) {
      var agingColors = ['#ef4444', '#f97316', '#f59e0b', '#10b981'];
      new ApexCharts(agingEl, {
        chart: { type: 'bar', height: 220, toolbar: { show: false } },
        series: [{ name: 'Open CAs', data: data.caAgingData }],
        plotOptions: { bar: { borderRadius: 4, columnWidth: '55%', distributed: true } },
        xaxis: { categories: data.caAgingLabels },
        colors: agingColors,
        dataLabels: { enabled: true, style: { fontSize: '10px', fontWeight: 700 } },
        grid: { borderColor: '#e2e8f0' },
        legend: { show: false },
        tooltip: { y: { formatter: function (v) { return v + ' actions'; } } },
      }).render();
    }
  }

  if (data.caMonthlyClose && data.caMonthlyClose.length) {
    var closeEl = document.getElementById('caCloseChart');
    if (closeEl) {
      var closeData = data.caMonthlyClose;
      new ApexCharts(closeEl, {
        chart: { type: 'line', height: 220, toolbar: { show: false } },
        series: [{ name: 'Closed', data: closeData.map(function (d) { return d.count; }) }],
        xaxis: { categories: closeData.map(function (d) { return d.month; }) },
        colors: ['#10b981'],
        stroke: { curve: 'smooth', width: 2 },
        fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05, stops: [0, 100] } },
        markers: { size: 4, hover: { size: 6 } },
        dataLabels: { enabled: false },
        grid: { borderColor: '#e2e8f0' },
        tooltip: { y: { formatter: function (v) { return v + ' CAs'; } } },
      }).render();
    }
  }

  var regionEl = document.getElementById('regionScoreChart');
  if (regionEl && data.regionScores && data.regionScores.length) {
    var regionData = data.regionScores;
    new ApexCharts(regionEl, {
      chart: { type: 'bar', height: Math.max(220, regionData.length * 42), toolbar: { show: false } },
      series: [{ name: 'Avg %', data: regionData.map(function (r) { return r.avg; }) }],
      plotOptions: { bar: { horizontal: true, borderRadius: 3, barHeight: '55%', distributed: true } },
      xaxis: { categories: regionData.map(function (r) { return r.name; }), max: 100 },
      yaxis: { labels: { style: { fontSize: '9px' } } },
      legend: { show: false },
      colors: regionData.map(function (r) { return r.avg >= 90 ? '#10b981' : r.avg >= 80 ? '#f59e0b' : '#ef4444'; }),
      dataLabels: { enabled: true, formatter: function (v) { return v + '%'; }, style: { fontSize: '9px', fontWeight: 700, colors: ['#fff'] }, offsetX: 20 },
      grid: { borderColor: '#e2e8f0' },
      tooltip: { y: { formatter: function (v) { return v + '%'; } } },
    }).render();
  }

  var topBottomEl = document.getElementById('topBottomChart');
  if (topBottomEl && data.top5Restaurants && data.bottom5Restaurants) {
    var topData = data.top5Restaurants;
    var bottomData = data.bottom5Restaurants;
    var allRest = [].concat(topData.slice().reverse(), bottomData);
    var allLabels = allRest.map(function (r) { return r.name; });
    var allVals = allRest.map(function (r) { return r.avg; });
    new ApexCharts(topBottomEl, {
      chart: { type: 'bar', height: Math.max(220, allRest.length * 38), toolbar: { show: false } },
      series: [{ name: 'Avg %', data: allVals }],
      plotOptions: { bar: { horizontal: true, borderRadius: 3, barHeight: '50%', distributed: true } },
      xaxis: { categories: allLabels, max: 100 },
      yaxis: { labels: { style: { fontSize: '9px' } } },
      colors: allVals.map(function (v) { return v >= 90 ? '#10b981' : v >= 80 ? '#f59e0b' : '#ef4444'; }),
      dataLabels: { enabled: true, formatter: function (v) { return v + '%'; }, style: { fontSize: '9px', fontWeight: 700, colors: ['#fff'] }, offsetX: 20 },
      grid: { borderColor: '#e2e8f0' },
      legend: { show: false },
      tooltip: { y: { formatter: function (v) { return v + '%'; } } },
    }).render();
  }

  if (data.restaurantTrendSeries && data.restaurantTrendSeries.length) {
    var restTrendSeries = data.restaurantTrendSeries;
    var restTrendMonths = data.restaurantTrendMonths;
    var restTrendSelect = document.getElementById('restaurantTrendSelect');
    var restTrendContainer = document.getElementById('restaurantTrendChart');
    if (restTrendSelect && restTrendContainer) {
      var restTrendChart = null;
      function buildRestOpts() {
        restTrendSelect.innerHTML = '<option value="__all__">All Restaurants</option>';
        restTrendSeries.forEach(function (s) {
          var opt = document.createElement('option');
          opt.value = s.name; opt.textContent = s.name; restTrendSelect.appendChild(opt);
        });
      }
      function renderRestTrend(selected) {
        var series = selected === '__all__' ? restTrendSeries : restTrendSeries.filter(function (s) { return s.name === selected; });
        if (restTrendChart) { restTrendChart.destroy(); }
        restTrendChart = new ApexCharts(restTrendContainer, {
          chart: { type: 'line', height: 260, toolbar: { show: false } },
          series: series,
          xaxis: { categories: restTrendMonths },
          yaxis: { min: 0, max: 100, labels: { formatter: function (v) { return v + '%'; } } },
          colors: [primaryColor, '#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b7d4', '#f97316', '#6366f1', '#14b8a6'],
          stroke: { curve: 'smooth', width: 2 },
          dataLabels: { enabled: false },
          markers: { size: 3, hover: { size: 5 } },
          legend: { show: false },
          grid: { borderColor: '#e2e8f0' },
          tooltip: { y: { formatter: function (v) { return v + '%'; } } },
        });
        restTrendChart.render();
      }
      buildRestOpts();
      renderRestTrend('__all__');
      restTrendSelect.addEventListener('change', function (e) { renderRestTrend(e.target.value); });
    }
  }
});
