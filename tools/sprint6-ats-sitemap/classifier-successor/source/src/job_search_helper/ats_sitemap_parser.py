"""ATS Corporation adapter for the host-owned sitemap membership reader."""
from . import ats_job_path
from .successfactors_sitemap import read_sitemap_membership

PARSER_READY = callable(ats_job_path.classify_job_path)


def parse_job_sitemap(xml: str) -> dict[str, str]:
    """Return posting ID -> canonical job URL on the official ATS board."""
    classifier = ats_job_path.classify_job_path
    if classifier is None:
        raise ValueError('No reviewed ATS job path classifier is installed.')
    return read_sitemap_membership(xml, 'jobs.atsautomation.com', classifier)
