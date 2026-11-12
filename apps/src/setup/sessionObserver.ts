// Loaded from bootstrap.ts before the app: from here on every write or reset
// of the stored session is seen by the in-memory session store, so requests
// can read the session from memory instead of the keystore.
import { installSessionObserver } from '../services/sessionStore';

installSessionObserver();
