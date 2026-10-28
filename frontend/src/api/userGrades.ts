// 帐号—年级范围:自动排课读当前帐号自己的年级范围(主任只排自己年级)。
// 任命主任不再走单独页面,改在教师档案里用年级主任开关(写同一批数据)。
// 年级是全校统一的数字,不绑定学期。

import { apiGet } from '@/api/client'

export const myGradeScopes = (): Promise<number[] | null> =>
  apiGet('/users/me/grade-scopes')
