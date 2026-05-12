document.addEventListener('DOMContentLoaded', () => {
  const data = window.memoryPlatformData;
  if (!data) return;

  // 1. Hero / Executive Summary
  document.getElementById('project-title').textContent = data.projectTitle;
  document.getElementById('project-thesis').textContent = data.thesis;
  const stackList = document.getElementById('stack-list');
  data.stack.forEach(item => {
    const div = document.createElement('div');
    div.className = 'stack-item';
    div.innerHTML = `<span class="name">${item.name}</span><span class="role">${item.role}</span>`;
    stackList.appendChild(div);
  });

  // 2. Architecture Map
  const archMap = document.getElementById('arch-map');
  data.architecture.layers.forEach(layer => {
    const div = document.createElement('div');
    div.className = 'arch-layer';
    div.innerHTML = `
      <h3>${layer.name}</h3>
      <div class="components">${layer.components.map(c => `<span class="comp">${c}</span>`).join('')}</div>
      <p class="notes">${layer.notes}</p>
    `;
    archMap.appendChild(div);
  });

  // 3. Responsibility Split
  const outsourceList = document.getElementById('outsource-list');
  data.responsibilitySplit.outsource.forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    outsourceList.appendChild(li);
  });
  const keepList = document.getElementById('keep-list');
  data.responsibilitySplit.keep.forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    keepList.appendChild(li);
  });

  // 4. Data Model
  const modelBody = document.getElementById('model-body');
  data.dataModel.fields.forEach(field => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${field.name}</strong></td>
      <td><span class="badge badge-planned">${field.group}</span></td>
      <td><span class="type-tag">${field.type}</span></td>
      <td>${field.desc}</td>
    `;
    modelBody.appendChild(tr);
  });

  // 6. Roadmap
  const roadmapTimeline = document.getElementById('roadmap-timeline');
  data.roadmap.forEach(phase => {
    const div = document.createElement('div');
    div.className = 'timeline-phase';
    div.innerHTML = `
      <div class="phase-number">${phase.phase}</div>
      <div class="phase-content">
        <div class="phase-header">
          <h3>${phase.title}</h3>
          <span class="badge badge-${phase.status.toLowerCase()}">${phase.status}</span>
        </div>
        <ul class="milestone-list">
          ${phase.milestones.map(m => `<li>${m}</li>`).join('')}
        </ul>
      </div>
    `;
    roadmapTimeline.appendChild(div);
  });

  // 7. Migration Order
  const migrationList = document.getElementById('migration-order');
  data.migration.order.forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    migrationList.appendChild(li);
  });

  // 8. Risks
  const riskGrid = document.getElementById('risk-grid');
  data.risks.forEach(risk => {
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <h4 style="margin:0">${risk.risk}</h4>
        <span class="badge badge-warning">${risk.impact} Impact</span>
      </div>
      <p style="font-size: 12px; color: var(--text-secondary); margin:0"><strong>Mitigation:</strong> ${risk.mitigation}</p>
    `;
    riskGrid.appendChild(div);
  });

  // 9. Task Board
  const taskBoard = document.getElementById('task-board');
  const renderTasks = (filter) => {
    taskBoard.innerHTML = '';
    const filteredTasks = data.tasks.filter(task => {
      if (filter === 'all') return true;
      if (filter === 'phase3') return task.phase >= 3;
      return `phase${task.phase}` === filter;
    });

    filteredTasks.forEach(task => {
      const div = document.createElement('div');
      div.className = 'card task-card';
      div.innerHTML = `
        <div style="display: flex; justify-content: space-between;">
          <span><span class="id">#${task.id}</span><strong>${task.title}</strong></span>
          <span class="badge badge-planned">P${task.phase}</span>
        </div>
        <p>${task.desc}</p>
      `;
      taskBoard.appendChild(div);
    });
  };
  renderTasks('all');

  // Task Filters
  const filterBtns = document.querySelectorAll('.filter-btn');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderTasks(btn.dataset.filter);
    });
  });

  // 10. Decision
  document.getElementById('config-skeleton').textContent = data.configSkeleton;
  document.getElementById('copy-config').addEventListener('click', () => {
    navigator.clipboard.writeText(data.configSkeleton).then(() => {
      const btn = document.getElementById('copy-config');
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = 'Copy', 2000);
    });
  });

  // Navigation Highlighting
  const sections = document.querySelectorAll('section');
  const navLinks = document.querySelectorAll('nav a');
  window.addEventListener('scroll', () => {
    let current = '';
    sections.forEach(section => {
      const sectionTop = section.offsetTop;
      if (pageYOffset >= sectionTop - 100) {
        current = section.getAttribute('id');
      }
    });

    navLinks.forEach(link => {
      link.classList.remove('active');
      if (link.getAttribute('href').slice(1) === current) {
        link.classList.add('active');
      }
    });
  });
});
