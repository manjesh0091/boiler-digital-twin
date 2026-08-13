// Central registry of data-testid values used throughout the app.
export const HOME = {
  emergentLink: "home-emergent-link",
};

export const NAV = {
  sidebar: "nav-sidebar",
  linkS01: "nav-link-pai-s01",
  linkS03: "nav-link-pai-s03",
  scenarioSelect: "nav-scenario-select",
  ackAll: "nav-ack-all",
  loadValue: "header-unit-load",
  modeValue: "header-mode",
  dqBadge: "header-dq-badge",
};

export const S01 = {
  root: "pai-s01-root",
  boiGauge: "pai-s01-boi-gauge",
  boiValue: "pai-s01-boi-value",
  boiSuppressed: "pai-s01-boi-suppressed",
  paramGrid: "pai-s01-param-grid",
  paramRow: (k) => `pai-s01-param-row-${k}`,
  waterfall: "pai-s01-waterfall",
  trendTabs: "pai-s01-trend-tabs",
  trendTab: (g) => `pai-s01-trend-tab-${g}`,
  trendChart: "pai-s01-trend-chart",
  alertList: "pai-s01-alert-list",
  ackBtn: (id) => `pai-s01-ack-${id}`,
  summary: "pai-s01-summary",
  safetyIncomplete: "pai-s01-safety-incomplete",
  crossValidation: "pai-s01-cross-validation",
  crossValidationRow: (rel) => `pai-s01-cross-validation-row-${rel}`,
};

export const S02 = {
  root: "pai-s02-root",
  effGauge: "pai-s02-efficiency-gauge",
  effGaugeValue: "pai-s02-efficiency-gauge-value",
  effGaugeDeviation: "pai-s02-efficiency-gauge-deviation",
  effGaugeCoFlag: "pai-s02-efficiency-gauge-co-flag",
  lossWaterfall: "pai-s02-loss-waterfall",
  coLossStub: "pai-s02-co-loss-stub",
  heatCreditsCard: "pai-s02-heat-credits-card",
  boilerDutyCard: "pai-s02-boiler-duty-card",
  gcvCheckCard: "pai-s02-gcv-check-card",
  enthalpyTable: "pai-s02-enthalpy-table",
  airFlueGasCard: "pai-s02-air-flue-gas-card",
  correctionsCard: "pai-s02-corrections-card",
  trendChart: "pai-s02-trend-chart",
  alertCards: "pai-s02-alert-cards",
  shiftSummaryTable: "pai-s02-shift-summary-table",
  dataQualityBadge: "pai-s02-data-quality-badge",
  assumptionsPanel: "pai-s02-assumptions-panel",
  warningsBanner: "pai-s02-warnings-banner",
  dataGapBanner: "pai-s02-data-gap-banner",
};

export const S03 = {
  root: "pai-s03-root",
  o2Gauge: "pai-s03-o2-gauge",
  eaBanner: "pai-s03-ea-banner",
  coIndicator: "pai-s03-co-indicator",
  coCriticalBanner: "pai-s03-co-critical-banner",
  quadrantPlot: "pai-s03-quadrant-plot",
  o2Trend: "pai-s03-o2-trend",
  afrStrip: "pai-s03-afr-strip",
  efficiencyCard: "pai-s03-efficiency-card",
  guidance: "pai-s03-guidance",
  cssBadge: "pai-s03-css-badge",
};
