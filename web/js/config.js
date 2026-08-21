// Local dev (served from localhost/127.0.0.1) hits the local API; anywhere
// else (the deployed Cloudflare site) hits the production Droplet API.
const API_BASE_URL =
  location.hostname === "localhost" || location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8000"
    : "https://165-22-246-179.sslip.io";

const SCALE_MAX = 11; // advantage % that maps to a full half-bar
const ROLES = ["Carry", "Midlane", "Offlane"];
const MAX_PICKS = 5;
