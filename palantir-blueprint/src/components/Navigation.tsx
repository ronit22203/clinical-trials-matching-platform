import { Button, Navbar, NavbarGroup, NavbarHeading, Tag, Intent } from "@blueprintjs/core";

interface NavigationProps {
  clinicianMode: boolean;
  theme: "solarized" | "slate";
  onModeToggle: () => void;
  onThemeToggle: () => void;
}

function ThemeIcon({ theme }: Pick<NavigationProps, "theme">) {
  if (theme === "solarized") {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="8" cy="8" r="3" />
        <path d="M8 1.5v1.25M8 13.25v1.25M1.5 8h1.25M13.25 8h1.25M3.4 3.4l.9.9M11.7 11.7l.9.9M12.6 3.4l-.9.9M4.3 11.7l-.9.9" />
      </svg>
    );
  }

  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M13.5 10.2A5.75 5.75 0 0 1 5.8 2.5a5.75 5.75 0 1 0 7.7 7.7Z" />
    </svg>
  );
}

export default function Navigation({ clinicianMode, theme, onModeToggle, onThemeToggle }: NavigationProps) {
  return (
    <Navbar className="app-navbar">
      <NavbarGroup className="app-navbar-brand">
        <NavbarHeading className="app-navbar-heading">
          Clinical Search
        </NavbarHeading>
      </NavbarGroup>
      <NavbarGroup align="right" className="app-navbar-actions">
        <Tag
          className="app-navbar-mode"
          minimal
          intent={clinicianMode ? Intent.PRIMARY : Intent.WARNING}
          title={clinicianMode ? "Clinical mode: simplified view for clinicians" : "Audit mode: full technical detail"}
        >
          {clinicianMode ? "CLINICAL" : "AUDIT"}
        </Tag>
        <span className="app-navbar-divider" aria-hidden="true" />
        <Button
          className="app-navbar-theme-toggle"
          minimal
          small
          aria-pressed={theme === "slate"}
          aria-label={theme === "solarized" ? "Switch to the Slate Gray theme" : "Switch to the Solarized Light theme"}
          icon={<ThemeIcon theme={theme} />}
          title={theme === "solarized" ? "Switch to the Slate Gray theme" : "Switch to the Solarized Light theme"}
          onClick={onThemeToggle}
          style={{ width: 28, minWidth: 28, padding: 0 }}
        />
        <Button
          className="app-navbar-mode-toggle"
          minimal
          small
          icon={clinicianMode ? "settings" : "pulse"}
          text={clinicianMode ? "Switch to Audit" : "Switch to Clinical"}
          onClick={onModeToggle}
        />
      </NavbarGroup>
    </Navbar>
  );
}
