import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from packages.storage.db import Base
from packages.storage.models import Paper, PaperTag
from packages.storage.repositories import PaperRepository, TagRepository


class TagRepositoryTest(unittest.TestCase):
    def test_delete_removes_paper_tag_links(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        with Session() as session:
            paper = Paper(
                arxiv_id="arxiv:tag-delete-demo",
                title="Tagged Paper",
                abstract="",
                metadata_json={},
            )
            session.add(paper)
            session.flush()

            tag_repo = TagRepository(session)
            tag = tag_repo.create("temporary", "#3b82f6")
            PaperRepository(session).link_to_tag(paper.id, tag.id)
            session.flush()

            self.assertEqual(tag_repo.get_paper_count(tag.id), 1)

            deleted_count = tag_repo.delete(tag.id)

            self.assertEqual(deleted_count, 1)
            self.assertIsNone(tag_repo.get_by_id(tag.id))
            link_count = session.execute(
                select(func.count()).select_from(PaperTag).where(PaperTag.tag_id == tag.id)
            ).scalar_one()
            self.assertEqual(link_count, 0)


if __name__ == "__main__":
    unittest.main()
