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
          System online
        </Tag>
        <Tag minimal style={{ opacity: 0.6, fontWeight: 400 }}>1.0</Tag>
      </NavbarGroup>
      <NavbarGroup align="right">
        {/* Current mode indicator */}
        <Tag
          minimal
          intent={clinicianMode ? Intent.PRIMARY : Intent.WARNING}
          style={{ fontFamily: "var(--text-mono)", fontSize: 9, letterSpacing: "0.06em", marginRight: 6 }}
          title={clinicianMode ? "Clinical mode: simplified view for clinicians" : "Audit mode: full technical detail"}
        >
          {clinicianMode ? "CLINICAL" : "AUDIT"}
        </Tag>
        <Button
          minimal
          small
          icon={clinicianMode ? "settings" : "pulse"}
          text={clinicianMode ? "Switch to Audit" : "Switch to Clinical"}
          onClick={onModeToggle}
          style={{ fontFamily: "var(--text-mono)", fontSize: 10, letterSpacing: "0.04em" }}
        />
      </NavbarGroup>
    </Navbar>
  );
}

