# Sprint 0 Backlog
**Duration:** Weeks 1-3 of Term 2  
**Status:** Completed  
**Goal:** Team formation, technical setup (Repo + Docker), and project preparation

## Sprint 0 Highlevel Objectives
1. Forming the team (4-5 members)
2. Setting up technical infrastructure
3. Understanding requirements and test cases
4. Planning Sprints 1-3

**Team Lead Responsibilities:**
- Coordinate weekly standups
- Manage GitHub Projects
- Lead sprint reviews
- Final submission coordination

## Sprint 0 Checklist

### Week 1: Team & Repository Setup
- [x] Team formed (4-5 members confirmed)
- [x] Communication channels established (MS Teams)
- [x] GitHub repository created
- [x] All team members added as collaborators
- [x] Everyone cloned repository locally
- [x] Docker Desktop installed on all machines
- [x] Initial README created
- [x] .gitignore configured
- [x] .env.example created

### Week 2: Technical Foundation
- [x] docker-compose.yml created with defined services
- [x] Each service has basic Django project initialized
- [x] All containers can start successfully
- [ ] Branch protection rules set on `main`
- [x] CONTRIBUTING.md guidelines documented
- [x] each team member does what is needed to catch up on and understand Docker and Django to prepare for Sprint 1 implementation

### Week 3: Planning & Analysis
- [x] BPMN diagrams analyzed (note: can be found inside the docs directory)
- [x] Test cases reviewed (when provided)
- [x] Each developer knows their Sprint 1 tasks
- [x] Architecture documented
- [x] API endpoints planned

## Team Formation

| Role | Service Ownership | Name |
|------|-------------------|-----------------|
| Team Lead | Frontend Service | Matt Wood |
| Developer | Customer API | Dina Metwalli |
| Developer | Platform API | Kaan Karadag |
| Developer | Producer API | Leon Stansfield |
| Developer | Payment Gateway | Amine Ziani |

**Note:** this structure was later changed in Sprint 1 when rethinking the project architecture and inter-service communication

## Sprint 0 Deliverables

### 1. Working Docker Environment
All team members should be able to run:
```bash
docker-compose up --build
```
And see all containers running successfully.

### 2. Initial Django Projects
Each service should have:
- `Dockerfile`
- `requirements.txt`
- Basic Django project created with `django-admin startproject`
- Can run migrations successfully

### 3. Sprint 1 Planning
Document in `docs/sprints/sprint-1-backlog.md`:
- Sprint 1 goals (aligned with marking criteria)
- Task breakdown
- Assignments

## Weekly Meeting Schedule

**Team Meetings:**
- Day: every Tuesday
- Time: 1 or 2 PM
- Duration: 1-2 hour(s)
- Location: In-person