import type { LoanOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface LoanBadgeProps {
  loan: LoanOut | null | undefined;
}

/** "Loaned to X". Used only by BookDetail. */
export default function LoanBadge({ loan }: LoanBadgeProps) {
  const { t } = useTranslation();
  if (!loan) return null;
  return (
    <span className="inline-flex items-center gap-1 bg-orange-100 text-orange-700 text-xs font-medium px-2.5 py-1 rounded-full dark:bg-orange-950 dark:text-orange-300">
      🤝 {t("loans.badge", { name: loan.loaned_to?.username ?? "" })}
    </span>
  );
}
