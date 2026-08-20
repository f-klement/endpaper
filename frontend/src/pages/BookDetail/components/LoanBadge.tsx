import type { LoanOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { Icon } from "../../../components";

interface LoanBadgeProps {
  loan: LoanOut | null | undefined;
}

/**
 * "Loaned to X". Used only by BookDetail.
 *
 * Two whole phrases rather than one with the name swapped in: a borrower with
 * no account is worth saying so, and German does not keep the English word
 * order that a concatenation would assume.
 */
export default function LoanBadge({ loan }: LoanBadgeProps) {
  const { t } = useTranslation();
  if (!loan) return null;
  return (
    <span className="inline-flex items-center gap-1 bg-orange-100 text-orange-700 text-xs font-medium px-2.5 py-1 rounded-full dark:bg-orange-950 dark:text-orange-300">
      <Icon name="handshake" className="w-3.5 h-3.5" />{" "}
      {/* On the name, not on `loaned_to`: that is a relationship, populated
          only where the caller joined it, while the name is the column the
          database constraint governs. */}
      {loan.loaned_to_name
        ? t("loans.badgeExternal", { name: loan.loaned_to_name })
        : t("loans.badge", { name: loan.loaned_to?.username ?? "" })}
    </span>
  );
}
