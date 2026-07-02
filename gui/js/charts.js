/* Chart rendering helpers built on TradingView lightweight-charts. */

const CHART_COLORS = {
  bg: "transparent",
  grid: "#1c232d",
  text: "#9fadbc",
  up: "#2ecc71",
  down: "#ef4444",
  fast: "#f5a623",
  slow: "#3b82f6",
  rsi: "#c084fc",
  strategy: "#3b82f6",
  benchmark: "#9fadbc",
};

function baseChartOptions(container) {
  return {
    width: container.clientWidth,
    height: container.clientHeight,
    layout: { background: { color: CHART_COLORS.bg }, textColor: CHART_COLORS.text, fontSize: 11 },
    grid: {
      vertLines: { color: CHART_COLORS.grid },
      horzLines: { color: CHART_COLORS.grid },
    },
    rightPriceScale: { borderColor: CHART_COLORS.grid },
    timeScale: { borderColor: CHART_COLORS.grid, timeVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: true,
    handleScale: true,
  };
}

function destroyChart(container) {
  if (container._chart) {
    try { container._chart.remove(); } catch (e) { /* already gone */ }
    container._chart = null;
  }
  container.innerHTML = "";
}

function tradeMarkers(trades) {
  const markers = [];
  (trades || []).forEach((t) => {
    markers.push({
      time: t.entry_date,
      position: "belowBar",
      color: CHART_COLORS.up,
      shape: "arrowUp",
      text: "buy",
    });
    if (t.exit_date) {
      markers.push({
        time: t.exit_date,
        position: "aboveBar",
        color: CHART_COLORS.down,
        shape: "arrowDown",
        text: "sell",
      });
    }
  });
  markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  return markers;
}

function renderPriceChart(containerId, chartData) {
  const container = document.getElementById(containerId);
  destroyChart(container);
  if (!chartData || !chartData.ohlc || chartData.ohlc.length === 0) return null;

  const chart = LightweightCharts.createChart(container, baseChartOptions(container));
  container._chart = chart;

  const candleSeries = chart.addCandlestickSeries({
    upColor: CHART_COLORS.up,
    downColor: CHART_COLORS.down,
    borderVisible: false,
    wickUpColor: CHART_COLORS.up,
    wickDownColor: CHART_COLORS.down,
  });
  candleSeries.setData(chartData.ohlc);
  candleSeries.setMarkers(tradeMarkers(chartData.trades));

  const indicators = chartData.indicators || {};
  if (indicators.sma_fast && indicators.sma_fast.length) {
    const s = chart.addLineSeries({ color: CHART_COLORS.fast, lineWidth: 2, title: "SMA fast" });
    s.setData(indicators.sma_fast);
  }
  if (indicators.sma_slow && indicators.sma_slow.length) {
    const s = chart.addLineSeries({ color: CHART_COLORS.slow, lineWidth: 2, title: "SMA slow" });
    s.setData(indicators.sma_slow);
  }
  if (indicators.sma && indicators.sma.length) {
    const s = chart.addLineSeries({ color: CHART_COLORS.slow, lineWidth: 2, title: "SMA" });
    s.setData(indicators.sma);
  }

  if (chartData.train_test_cutoff) {
    candleSeries.createPriceLine; // no-op placeholder to keep candleSeries referenced
    chart.timeScale().fitContent();
  }

  chart.timeScale().fitContent();
  return chart;
}

function renderIndicatorChart(containerId, chartData) {
  const container = document.getElementById(containerId);
  const indicators = chartData ? chartData.indicators || {} : {};
  const hasRsi = indicators.rsi && indicators.rsi.length;
  const hasRoc = indicators.roc && indicators.roc.length;

  if (!hasRsi && !hasRoc) {
    destroyChart(container);
    container.classList.add("hidden");
    return null;
  }
  container.classList.remove("hidden");
  destroyChart(container);

  const chart = LightweightCharts.createChart(container, baseChartOptions(container));
  container._chart = chart;

  if (hasRsi) {
    const s = chart.addLineSeries({ color: CHART_COLORS.rsi, lineWidth: 2, title: "RSI(14)" });
    s.setData(indicators.rsi);
    s.createPriceLine({ price: 70, color: CHART_COLORS.down, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: "70" });
    s.createPriceLine({ price: 30, color: CHART_COLORS.up, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: "30" });
  } else if (hasRoc) {
    const s = chart.addLineSeries({ color: CHART_COLORS.rsi, lineWidth: 2, title: "ROC(10)" });
    s.setData(indicators.roc);
    s.createPriceLine({ price: 0, color: CHART_COLORS.text, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: "0" });
  }

  chart.timeScale().fitContent();
  return chart;
}

function renderEquityChart(containerId, chartData) {
  const container = document.getElementById(containerId);
  destroyChart(container);
  if (!chartData || !chartData.equity_curve || chartData.equity_curve.length === 0) return null;

  const chart = LightweightCharts.createChart(container, baseChartOptions(container));
  container._chart = chart;

  const strategySeries = chart.addLineSeries({ color: CHART_COLORS.strategy, lineWidth: 2, title: "Strategy" });
  const benchmarkSeries = chart.addLineSeries({ color: CHART_COLORS.benchmark, lineWidth: 2, title: "Buy & Hold" });

  strategySeries.setData(chartData.equity_curve.map((p) => ({ time: p.time, value: p.strategy })));
  benchmarkSeries.setData(chartData.equity_curve.map((p) => ({ time: p.time, value: p.benchmark })));

  if (chartData.train_test_cutoff) {
    strategySeries.createPriceLine; // keep reference alive
  }

  chart.timeScale().fitContent();
  return chart;
}

function resizeChart(containerId) {
  const container = document.getElementById(containerId);
  if (container && container._chart) {
    container._chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
  }
}

function renderBacktestCharts(priceId, indicatorId, equityId, chartData) {
  renderPriceChart(priceId, chartData);
  renderIndicatorChart(indicatorId, chartData);
  renderEquityChart(equityId, chartData);
}

window.Charts = {
  renderPriceChart,
  renderIndicatorChart,
  renderEquityChart,
  renderBacktestCharts,
  resizeChart,
  destroyChart,
};
