import { useTranslation } from "../i18n";

interface AboutProps {
  onBack: () => void;
}

export default function About({ onBack }: AboutProps) {
  const { t } = useTranslation();

  return (
    <div className="about-page">
      <button className="about-back" onClick={onBack}>
        &larr; {t.backToEvents}
      </button>

      <div className="about-card">
        <h2 className="about-greeting">{t.aboutGreeting}</h2>
        <p>{t.aboutIntro}</p>
        <p>{t.aboutProject}</p>
        <p>{t.aboutFuture}</p>

        <div className="about-links">
          <a
            href="https://github.com/MiruVL/events"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t.aboutGithub}
          </a>
          <a href="mailto:miru.a.lok@gmail.com">{t.aboutEmail}</a>
        </div>
      </div>
    </div>
  );
}
