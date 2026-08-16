/**
 * src/main.jsx
 * -------------
 * React entry point. Mounts the App component into #root (index.html).
 * Also imports the global CSS so it applies to every page.
 */

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);