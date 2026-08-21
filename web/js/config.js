// Update for production deploys - point at wherever the FastAPI backend lives.
const API_BASE_URL = "http://127.0.0.1:8000";

const SCALE_MAX = 11; // advantage % that maps to a full half-bar
const ROLES = ["Carry", "Midlane", "Offlane"];
const MAX_PICKS = 5;
