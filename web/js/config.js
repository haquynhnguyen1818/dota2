// Local dev (served from localhost/127.0.0.1) hits the local API; anywhere
// else (the deployed Cloudflare site) hits the production Droplet API.
const API_BASE_URL =
  location.hostname === "localhost" || location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8000"
    : "https://165-22-246-179.sslip.io";

const SCALE_MAX = 11; // advantage % that maps to a full half-bar
const ROLES = ["Carry", "Midlane", "Offlane", "Support"];

// The role sheet names the list "Supports"; the UI says "Support", matching the
// draft page's tab. setupCombo uses each option as both label and value, so the
// label is what ROLES holds and this maps it back at the one call site that
// talks to the API. Only names that differ need an entry.
const ROLE_API_NAME = { Support: "Supports" };

const MAX_PICKS = 5;
