/**
 * ScholarMind - 入口文件
 * @author ScholarMind Team
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import DesktopBootstrap from "./DesktopBootstrap";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DesktopBootstrap />
  </StrictMode>
);
