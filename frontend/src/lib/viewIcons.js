import {
  BookOpenText,
  BookUser,
  ClipboardCheck,
  Feather,
  FileInput,
  GitBranch,
  GraduationCap,
  Home,
  Library,
  Microscope,
  PlayCircle,
  Radar,
  Route,
  ScrollText,
  Settings2,
  ShieldCheck,
  Snowflake,
  Trash2,
  UploadCloud,
} from "lucide-vue-next";

export const VIEW_ICONS = {
  BookOpenText,
  BookUser,
  ClipboardCheck,
  Feather,
  FileInput,
  GitBranch,
  GraduationCap,
  Home,
  Library,
  Microscope,
  PlayCircle,
  Radar,
  Route,
  ScrollText,
  Settings2,
  ShieldCheck,
  Snowflake,
  Trash2,
  UploadCloud,
};

export function iconForView(view) {
  return VIEW_ICONS[view?.icon] || PlayCircle;
}
