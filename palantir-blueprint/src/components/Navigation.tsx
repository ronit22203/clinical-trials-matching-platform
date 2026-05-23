import { Button, Navbar, NavbarGroup, NavbarHeading, NavbarDivider, Tag, Intent } from "@blueprintjs/core";

interface NavigationProps {
  clinicianMode: boolean;
  onModeToggle: () => void;
}

export default function Navigation({ clinicianMode, onModeToggle }: NavigationProps) {
  return (
    <Navbar style={{ padding: "0 16px" }}>
      <NavbarGroup>
        <NavbarHeading style={{ fontWeight: 500, letterSpacing: "0.02em" }}>
          ClinicalSearch
        </NavbarHeading>
        <NavbarDivider />
        <Tag minimal intent={Intent.SUCCESS} style={{ fontWeight: 400 }}>
          System ready
        </Tag>
        <Tag minimal style={{ opacity: 0.6, fontWeight: 400 }}>v2026.05</Tag>
      </NavbarGroup>
      <NavbarGroup align="right">
        <Button
          minimal
          small
          icon={clinicianMode ? "settings" : "person"}
          text={clinicianMode ? "Audit View" : "Clinical View"}
          onClick={onModeToggle}
          style={{ fontFamily: "var(--text-mono)", fontSize: 10, letterSpacing: "0.04em" }}
        />
      </NavbarGroup>
    </Navbar>
  );
}

