// Frontend runtime config (loaded by login.html and index.html before their scripts).
//
// LOCAL DEV:  leave LEAVE_API_BASE as '' — pages on localhost / 127.0.0.1 talk to
//             the FastAPI server at http://localhost:8000 automatically.
// PRODUCTION: set it to the public URL of the deployed backend (no trailing slash),
//             e.g. 'https://leave-agent-api.onrender.com'. Without it, a deployed
//             site has no API to call and sign-in will report that it can't reach one.
window.LEAVE_API_BASE = '';
