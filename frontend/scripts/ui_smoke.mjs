import { chromium } from "playwright";

const baseUrl = process.env.UI_BASE_URL || "http://127.0.0.1:5173";
const password = process.env.AUTH_PASSWORD || "";

const routes = [
  { path: "/", name: "Agent" },
  { path: "/recommendation", name: "Compass" },
  { path: "/radar", name: "DailyRadar" },
  { path: "/papers", name: "Papers" },
  { path: "/collect", name: "Collect" },
  { path: "/wiki", name: "Wiki" },
  { path: "/brief", name: "DailyBrief" },
  { path: "/dashboard", name: "Dashboard" },
  { path: "/statistics", name: "Statistics" },
  { path: "/settings", name: "Settings" },
];

function interestingFailure(request) {
  const url = request.url();
  if (url.startsWith("data:") || url.includes("favicon")) return false;
  const failure = request.failure();
  if (!failure) return false;
  const text = failure.errorText || "";
  return !/net::ERR_ABORTED|NS_BINDING_ABORTED/.test(text);
}

function apiBaseFromUiBase(url) {
  const parsed = new URL(url);
  return `${parsed.protocol}//${parsed.hostname}:8000`;
}

async function loginByApi(context) {
  if (!password) return;
  const resp = await context.request.post(`${apiBaseFromUiBase(baseUrl)}/auth/login`, {
    data: { password },
  });
  if (!resp.ok()) return;
  const body = await resp.json();
  const token = body.access_token;
  await context.addInitScript((value) => {
    window.localStorage.setItem("auth_token", value);
  }, token);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const issues = [];
  const routeResults = [];

  await loginByApi(context);
  const page = await context.newPage();

  page.on("console", (msg) => {
    if (msg.type() === "error") {
      issues.push({ type: "console", text: msg.text(), url: page.url() });
    }
  });
  page.on("pageerror", (err) => {
    issues.push({ type: "pageerror", text: err.message, url: page.url() });
  });
  page.on("requestfailed", (request) => {
    if (interestingFailure(request)) {
      issues.push({
        type: "requestfailed",
        text: `${request.failure()?.errorText || "failed"} ${request.method()} ${request.url()}`,
        url: page.url(),
      });
    }
  });
  page.on("response", (response) => {
    const status = response.status();
    const url = response.url();
    if (status >= 500 && !url.includes("/agent/chat")) {
      issues.push({ type: "http", text: `${status} ${url}`, url: page.url() });
    }
  });

  for (const route of routes) {
    const before = issues.length;
    const target = `${baseUrl}${route.path}`;
    await page.goto(target, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1200);
    const title = await page.title().catch(() => "");
    const bodyText = await page
      .locator("body")
      .innerText({ timeout: 5000 })
      .catch((err) => `ERR:${err.message}`);
    const hasErrorBoundary = /页面出错|Something went wrong|Cannot read properties|ERR:/.test(bodyText);
    const hasNetworkError = /网络连接失败|Failed to fetch|NetworkError/.test(bodyText);
    const blank = bodyText.trim().length < 20;
    if (hasErrorBoundary || blank) {
      issues.push({
        type: "render",
        text: `${route.name} render suspicious: blank=${blank} errorBoundary=${hasErrorBoundary}`,
        url: target,
      });
    }
    routeResults.push({
      route: route.path,
      name: route.name,
      title,
      textSample: bodyText.trim().slice(0, 140).replace(/\s+/g, " "),
      newIssues: issues.length - before,
      hasNetworkError,
    });
  }

  await browser.close();
  console.log(JSON.stringify({ baseUrl, routeResults, issues }, null, 2));
  if (issues.length) process.exitCode = 2;
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
